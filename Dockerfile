FROM alpine:3.3
ADD . /src
WORKDIR /src
RUN apk add --no-cache python py-pip git
RUN pip install -r requirements.txt
RUN pip install git+git://github.com/andymccurdy/redis-py.git@master
ENTRYPOINT ["python", "app.py"]
