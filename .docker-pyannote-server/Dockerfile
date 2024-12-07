FROM python:3.11-slim-bullseye

ARG TORCH_CPU

ENV LANGUAGE=en_US.UTF-8
ENV PGCLIENTENCODING utf8
ENV PYTHONIOENCODING utf8
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /root

# install apt requirements

COPY .docker-pyannote-server/pkglist /root/pkglist
RUN set -x; apt-get update -y && apt-get install -f -y --no-install-recommends $(cat /root/pkglist) && apt-get clean

# install python requirements

COPY .docker-pyannote-server/requirements.cpu.txt /root/requirements.cpu.txt
COPY .docker-pyannote-server/requirements.cuda.txt /root/requirements.cuda.txt

RUN if [ "$TORCH_CPU" = "1" ]; then \
        pip install --no-cache-dir --upgrade -r /root/requirements.cpu.txt; \
    else \
        pip install --no-cache-dir --upgrade -r /root/requirements.cuda.txt; \
    fi

COPY .docker-pyannote-server/requirements.txt /root/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /root/requirements.txt

# copy server script

COPY .docker-pyannote-server/server.py /root/server.py
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
