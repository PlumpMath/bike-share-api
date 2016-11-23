from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
import json
import redis
import requests

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/bikes.db'
db = SQLAlchemy(app)
redis = redis.StrictRedis(host='redis', port='6379')

bike_data_url = 'https://bmorebikeshare.com/stations/'


class Station(db.Model):
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


@app.route('/', methods=['GET', 'POST'])
def index():
    """Returns all stations."""
    if request.method == 'GET':
        stations = [
            s.serialize() for s in Station.query.all()
            if s.station_type == 'OPEN']
        if not stations:
            # Need to populate table from blob.
            stations_data = json.loads(requests.get(bike_data_url).text)
            for s in stations_data:
                station = Station(
                        id=s['id'],
                        station_status=s['station_stocking_status'],
                        name=s['name'],
                        description=s['description'],
                        has_kiosk=s['has_kiosk'],
                        has_ccreader=s['has_ccreader'],
                        station_type=s['type'],
                        latitude=s['location'][0],
                        longitude=s['location'][1])
                db.session.add(station)

                soup = BeautifulSoup(s['popup'], 'html.parser')
                bikes = int(soup.select('span.station-bikes b')[0].string)
                docks = int(soup.select('span.station-docks b')[0].string)
                redis.hmset(s['name'], {'bikes': bikes, 'docks': docks})

            db.session.commit()

            stations = [
                s.serialize() for s in Station.query.all()
                if s.station_type == 'OPEN']

        for s in stations:
            s['bikes'] = redis.hget(s['name'], 'bikes')
            s['docks'] = redis.hget(s['name'], 'docks')

        return jsonify(stations)
    elif request.method == 'POST':
        longitude = request.args.get('longitude', None)
        latitude = request.args.get('latitude', None)
        num_stations = request.args.get('n', None)
        if (longitude is not None and
                latitude is not None and
                num_stations is not None):
            stations = {}
            return jsonify(stations)
        else:
            return "Missing arguments", 400


if __name__ == '__main__':
    app.run('0.0.0.0', port=5000, debug=True)
