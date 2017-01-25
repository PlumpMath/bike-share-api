from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
import hashlib
import json
import logging
import redis
import requests
from sqlalchemy.orm.exc import NoResultFound
import schedule
import time

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/bikes.db'
db = SQLAlchemy(app)
redis = redis.StrictRedis(host='redis', port='6379')
log = logging.getLogger(__name__)

bike_data_url = 'https://bmorebikeshare.com/stations/'


class Station(db.Model):
    """SQL Model for bike stations. Includes non-emphemeral information."""
    id = db.Column(db.String(36), primary_key=True)
    station_status = db.Column(db.String(16), nullable=False)
    name = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(128), nullable=False)
    has_kiosk = db.Column(db.Boolean(), default=False)
    has_ccreader = db.Column(db.Boolean(), default=False)
    station_type = db.Column(db.String(16), nullable=False)
    latitude = db.Column(db.Float(), nullable=False)
    longitude = db.Column(db.Float(), nullable=False)

    def serialize(self):
        return {
            'id': self.id,
            'station_status': self.station_status,
            'name': self.name,
            'description': self.description,
            'has_kiosk': self.has_kiosk,
            'has_ccreader': self.has_ccreader,
            'station_type': self.station_type,
            'latitude': self.latitude,
            'longitude': self.longitude
        }

db.create_all()


@app.route('/', methods=['GET'])
def stations():
    """Returns all open stations in the bike share program."""
    stations = [
        s.serialize() for s in Station.query.all()
        if s.station_type == 'OPEN']

    for s in stations:
        s['bikes'] = redis.hget(s['name'], 'bikes')
        s['docks'] = redis.hget(s['name'], 'docks')

    return jsonify(stations)


@app.route('/nearest', methods=['GET'])
def nearest_station():
    """Returns the nearest open bike station to a given set of coordinates.
    If there are no stations within 10 miles, this will return nothing.
    
    If a latitude and longitude are not provided in the request, an error will
    be returned acknowledging such."""

    latitude = request.args.get('latitude', None)
    longitude = request.args.get('longitude', None)

    if latitude and longitude:
        nearest_stations = redis.georadius(
            'stations', latitude, longitude, 10, unit='mi', count=10, sort='ASC')

        if not nearest_stations:
            return 'No nearby stations to {},{}'.format(
                latitude, longitude), 404 

        for name in nearest_stations:
            try:
                station = (Station.query.filter_by(
                    name=name, station_type='OPEN').one()).serialize()
                break
            except NoResultFound:
                log.info('Station "{}" is not open.'.format(name))

        station['bikes'] = redis.hget(station['name'], 'bikes')
        station['docks'] = redis.hget(station['name'], 'docks')
        return jsonify(station)
    else:
        return "Latitude and longitude not provided.", 400
                                            

@app.route('/<name>', methods=['GET'])
def station_by_name(name):
    """Returns a station by given name. If no station exists with the given
    name, returns a 404."""

    try:
        station = (Station.query.filter_by(name=name).one()).serialize()
        station['bikes'] = redis.hget(station['name'], 'bikes')
        station['docks'] = redis.hget(station['name'], 'docks')
        return jsonify(station)
    except NoResultFound:
        return "No station found named {name}".format(name=name), 404


def get_stations():
    """Setup function to populate stations table if no data exists. Should only
    be run once."""
    resp = requests.get(bike_data_url).text
    hashed = hashlib.sha256(resp).hexdigest()
    redis.set('station_data', hashed)
    redis.set('bike_data', hashed)
    stations_data = json.loads(resp)
    for s in stations_data:
        latitude, longitude = s['location']
        station = Station(
                id=s['id'],
                station_status=s['station_stocking_status'],
                name=s['name'],
                description=s['description'],
                has_kiosk=s['has_kiosk'],
                has_ccreader=s['has_ccreader'],
                station_type=s['type'],
                latitude=latitude,
                longitude=longitude)
        db.session.add(station)

        soup = BeautifulSoup(s['popup'], 'html.parser')
        bikes = int(soup.select('span.station-bikes b')[0].string)
        docks = int(soup.select('span.station-docks b')[0].string)
        redis.hmset(s['name'], {'bikes': bikes, 'docks': docks})
        redis.geoadd('stations', latitude, longitude, s['name'])

    db.session.commit()


def update_bike_counts():
    """Job function to update bike and dock counts for all stations on a
    schedule."""
    log.info('Updating bike counts.')
    resp = requests.get(bike_data_url).text
    hashed = hashlib.sha256(resp).hexdigest()
    if hashed == redis.get('bike_data'):
        log.info('Dataset has not changed.')
        return
    else:
        redis.set('bike_data', hashed)
        stations_data = json.loads(resp)
        for s in stations_data: 
            soup = BeautifulSoup(s['popup'], 'html.parser')
            bikes = int(soup.select('span.station-bikes b')[0].string)
            docks = int(soup.select('span.station-docks b')[0].string)
            redis.hmset(s['name'], {'bikes': bikes, 'docks': docks})


def update_stations():
    """Helper function to update rarely changing station data on a schedule."""
    log.info('Updating stations.')
    resp = requests.get(bike_data_url).text
    hashed = hashlib.sha256(resp).hexdigest()
    if hashed == redis.get('station_data'):
        log.info('Dataset has not changed.')
        return
    else:
        redis.set('station_data')
        stations_data = json.loads(resp)
        for s in stations_data:
            station = Station.query.filter_by(name=s['name'])
            station.station_status = s['station_stocking_status']
            station.station_type = s['type']
        db.session.commit()


schedule.every(15).minutes.do(update_bike_counts)
schedule.every().day.do(update_stations)


if __name__ == '__main__':
    stations = Station.query.all()
    if not stations:
        get_stations()
    app.run('0.0.0.0', port=5000, debug=True)
    
    while True:
        schedule.run_pending()
        time.sleep(1)
