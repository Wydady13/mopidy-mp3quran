FROM python:3.13-slim

ARG SNAPCAST_VERSION=0.35.0
ARG SNAPWEB_VERSION=0.9.3
ARG MOPIDY_USER=mopidy

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    python3-gst-1.0 \
    gir1.2-gtk-4.0 \
    libcairo2-dev \
    libgirepository-2.0-dev \
    xdg-user-dirs \
    ca-certificates \
    curl \
    gnupg

RUN ARCH=$(dpkg --print-architecture) && \
    DEBIAN_CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME") && \
    SNAPSERVER_DEB="snapserver_${SNAPCAST_VERSION}-1_${ARCH}_${DEBIAN_CODENAME}.deb" && \
    curl -sSL -o "/tmp/${SNAPSERVER_DEB}" "https://github.com/snapcast/snapcast/releases/download/v${SNAPCAST_VERSION}/${SNAPSERVER_DEB}" && \
    if curl -sSL -o "/tmp/${SNAPSERVER_DEB}.sha256sum" "https://github.com/snapcast/snapcast/releases/download/v${SNAPCAST_VERSION}/${SNAPSERVER_DEB}.sha256sum" 2>/dev/null; then \
        cd /tmp && sha256sum -c "${SNAPSERVER_DEB}.sha256sum"; \
    else \
        echo "Warning: Checksum file not found, skipping verification"; \
    fi && \
    apt-get install -y --no-install-recommends "/tmp/${SNAPSERVER_DEB}" && \
    SNAPWEB_DEB="snapweb_${SNAPWEB_VERSION}-1_all.deb" && \
    curl -sSL -o "/tmp/${SNAPWEB_DEB}" "https://github.com/snapcast/snapweb/releases/download/v${SNAPWEB_VERSION}/${SNAPWEB_DEB}" && \
    if curl -sSL -o "/tmp/${SNAPWEB_DEB}.sha256sum" "https://github.com/snapcast/snapweb/releases/download/v${SNAPWEB_VERSION}/${SNAPWEB_DEB}.sha256sum" 2>/dev/null; then \
        cd /tmp && sha256sum -c "${SNAPWEB_DEB}.sha256sum"; \
    else \
        echo "Warning: Checksum file not found, skipping verification"; \
    fi && \
    apt-get install -y --no-install-recommends "/tmp/${SNAPWEB_DEB}"

RUN apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/*.deb /tmp/*.sha256sum && \
    mkdir -p /var/lib/mopidy/media /audio

RUN pip install --no-cache-dir mopidy-mpd

COPY . /src/mopidy-mp3quran
RUN pip install --no-cache-dir /src/mopidy-mp3quran && \
    rm -rf /src/mopidy-mp3quran

COPY docker/snapserver.conf /etc/snapserver.conf
COPY docker/mopidy.conf /etc/mopidy/mopidy.conf

RUN useradd -m -u 1000 ${MOPIDY_USER} && \
    mkdir -p /var/lib/mopidy /var/cache/mopidy /etc/mopidy /audio && \
    chown -R ${MOPIDY_USER}:${MOPIDY_USER} /var/lib/mopidy /var/cache/mopidy /etc/mopidy /audio && \
    mkfifo /audio/snapfifo && \
    chown ${MOPIDY_USER}:${MOPIDY_USER} /audio/snapfifo

EXPOSE 6600 6680 1704 1705 1780

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -fsS -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"core.get_uri_schemes"}' http://localhost:6680/mopidy/rpc || exit 1

USER ${MOPIDY_USER}

ENTRYPOINT ["/entrypoint.sh"]
CMD ["mopidy", "--verbose"]
