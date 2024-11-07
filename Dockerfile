FROM python:3.10

WORKDIR /app/

COPY ./requirements.docker.txt /app/requirements.txt
RUN pip install -r requirements.txt --root-user-action=ignore

COPY ./*.py /app/
COPY ./dependencies/ /app/dependencies
COPY ./models /app/models
COPY ./routers /app/routers

ARG GIT_VERSION=unknown

ENV VERSION=${GIT_VERSION}

ENTRYPOINT [ "uvicorn", "main:app", "--host", "0.0.0.0" ]
