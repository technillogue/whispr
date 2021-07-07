FROM ghcr.io/graalvm/graalvm-ce:latest as sigbuilder
ENV GRAALVM_HOME=/opt/graalvm-ce-java11-21.1.0/ 
SHELL ["/usr/bin/bash", "-c"]
WORKDIR /app
RUN microdnf install -y git zlib-devel && rm -rf /var/cache/yum
RUN gu install native-image
RUN git clone https://github.com/forestcontact/signal-cli
WORKDIR /app/signal-cli
RUN git fetch -a && git checkout stdio-generalized # shrug
RUN ./gradlew build && ./gradlew installDist
RUN md5sum ./build/libs/* 
RUN ./gradlew assembleNativeImage

FROM ubuntu:hirsute as libbuilder
WORKDIR /app
RUN ln --symbolic --force --no-dereference /usr/share/zoneinfo/EST && echo "EST" > /etc/timezone
RUN apt update
RUN DEBIAN_FRONTEND="noninteractive" apt install -yy python3.9  python3.9-venv pipenv
RUN python3.9 -m venv /app/venv
COPY pyproject.toml poetry.lock requirements.txt /app/
RUN VIRTUAL_ENV=/app/venv pipenv install -r requirements.txt
#RUN VIRTUAL_ENV=/app/venv pipenv run pip uninstall dataclasses -y

FROM ubuntu:hirsute
WORKDIR /app
RUN mkdir -p /app/data
RUN apt update
RUN apt install -y python3.9 npm && sudo npm install -g localtunnel #wget libfuse2 kmod
#RUN apt-get clean autoclean && apt-get autoremove --yes && rm -rf /var/lib/{apt,dpkg,cache,log}/


COPY --from=sigbuilder /app/signal-cli/build/native-image/signal-cli /app
COPY --from=sigbuilder /lib64/libz.so.1 /lib64
COPY --from=libbuilder /app/venv/lib/python3.9/site-packages /app/
# i understand that by copying data i include the secret key, which is bad
COPY ./whispr.py ./form.html ./listener.py ./server_number ./teli ./admins /app/ 
COPY ./data/+18057197864 /app/data/+18057197864 
RUN ls /app
ENTRYPOINT ["/usr/bin/python3.9", "/app/whispr.py"]
