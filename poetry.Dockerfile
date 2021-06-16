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
RUN apt updat 
RUN apt install -yy pipx && pipx install poetry
COPY pypoetry.toml poetry.lock /app/
RUN poetry install --no-root --no-dev


FROM ubuntu:hirsute
WORKDIR /app
COPY --from=sigbuilder /lib64/libz.so.1 /lib64
COPY --from=sigbuilder /app/signal-cli/build/native-image/signal-cli /app
COPY --from=libbuilder /app /app
COPY ./whispr.py ./form.html, ./listener.py, ./server_number, ./admins /app/
ENTRYPOINT ["/usr/bin/python3.9", "/app/whispr.py"]
