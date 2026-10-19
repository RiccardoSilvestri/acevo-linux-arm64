FROM ubuntu:22.04

ARG WINE_VERSION=11.12
ARG WINE_FLAVOR=staging
ARG DEPOTDOWNLOADER_VERSION=latest
ARG WINE_MIN_REG_KEYS=5000

ENV DEBIAN_FRONTEND=noninteractive
ENV WINEARCH=win64
ENV WINEPREFIX=/wine
ENV BOX64_LOG=0
ENV BOX64_BASH_WAIT=0

RUN apt-get update && apt-get install -y \
    wget curl ca-certificates unzip xz-utils \
    libglib2.0-0 libglib2.0-dev \
    libfreetype6 libfontconfig1 \
    libgcc-s1 libstdc++6 \
    libc6 \
    libpulse0 libasound2 \
    libdbus-1-3 libxml2 \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

COPY box64 /usr/local/bin/box64
COPY box64.box64rc /etc/box64.box64rc
RUN chmod +x /usr/local/bin/box64

COPY x86_64-libs/ /usr/lib/x86_64-linux-gnu/

RUN mkdir -p /opt/wine && \
    wget -q "https://github.com/Kron4ek/Wine-Builds/releases/download/${WINE_VERSION}/wine-${WINE_VERSION}-${WINE_FLAVOR}-amd64.tar.xz" \
    -O /tmp/wine.tar.xz && \
    tar -xf /tmp/wine.tar.xz -C /opt/wine --strip-components=1 && \
    rm /tmp/wine.tar.xz && \
    echo "Wine installed: $(ls /opt/wine/bin/)"

ENV PATH="/opt/wine/bin:${PATH}"

RUN if [ "$DEPOTDOWNLOADER_VERSION" = "latest" ]; then \
        TAG=$(curl -s https://api.github.com/repos/SteamRE/DepotDownloader/releases/latest | grep '"tag_name"' | cut -d'"' -f4); \
    else TAG="$DEPOTDOWNLOADER_VERSION"; fi && \
    echo "DepotDownloader release: $TAG" && \
    wget -q "https://github.com/SteamRE/DepotDownloader/releases/download/${TAG}/DepotDownloader-linux-arm64.zip" \
    -O /tmp/depotdownloader.zip && \
    mkdir -p /opt/depotdownloader && \
    unzip -q /tmp/depotdownloader.zip -d /opt/depotdownloader && \
    chmod +x /opt/depotdownloader/DepotDownloader && \
    rm /tmp/depotdownloader.zip && \
    echo "DepotDownloader ready"

RUN mkdir -p /wine && \
    WINEDEBUG=-all WINEPREFIX=/wine wine wineboot --init && \
    WINEPREFIX=/wine wineserver -w && \
    KEYS=$(grep -c '^\[' /wine/system.reg) && \
    echo "Wine prefix ready ($KEYS registry keys)" && \
    if [ "$KEYS" -lt "$WINE_MIN_REG_KEYS" ]; then echo "Wine prefix incomplete: $KEYS keys"; exit 1; fi

COPY scripts/ /scripts/
RUN chmod +x /scripts/*.sh

VOLUME ["/data"]

EXPOSE 9600/udp 9600/tcp 8000/tcp

WORKDIR /data

ENTRYPOINT ["/scripts/entrypoint.sh"]
