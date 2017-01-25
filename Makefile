all:
	docker build -t bike_share_api .
	docker-compose up -d

clean:
	docker-compose down
