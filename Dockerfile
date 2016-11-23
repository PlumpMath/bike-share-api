FROM alpine:3.3
ADD . /src
WORKDIR /src
RUN apk add --no-cache python py-pip
RUN pip install -r requirements.txt
ENTRYPOINT ["python", "app.py"]
