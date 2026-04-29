FROM python:3.10-slim

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
    curl -sSL -o /tmp/snapserver.deb "https://github.com/snapcast/snapcast/releases/download/v${SNAPCAST_VERSION}/snapserver_${SNAPCAST_VERSION}-1_${ARCH}_${DEBIAN_CODENAME}.deb" && \
    curl -sSL -o /tmp/snapserver.deb.sha256 "https://github.com/snapcast/snapcast/releases/download/v${SNAPCAST_VERSION}/snapserver_${SNAPCAST_VERSION}-1_${ARCH}_${DEBIAN_CODENAME}.deb.sha256sum" && \
    (cd /tmp && sha256sum -c snapserver.deb.sha256) && \
    apt-get install -y --no-install-recommends /tmp/snapserver.deb && \
    curl -sSL -o /tmp/snapweb.deb "https://github.com/snapcast/snapweb/releases/download/v${SNAPWEB_VERSION}/snapweb_${SNAPWEB_VERSION}-1_all.deb" && \
    curl -sSL -o /tmp/snapweb.deb.sha256 "https://github.com/snapcast/snapweb/releases/download/v${SNAPWEB_VERSION}/snapweb_${SNAPWEB_VERSION}-1_all.deb.sha256sum" && \
    (cd /tmp && sha256sum -c snapweb.deb.sha256) && \
    apt-get install -y --no-install-recommends /tmp/snapweb.deb

RUN apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/snapserver.deb /tmp/snapweb.deb /tmp/*.sha256 && \
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
    CMD curl -f http://localhost:6680/mopidy/rpc || exit 1

USER ${MOPIDY_USER}

ENTRYPOINT ["/entrypoint.sh"]
CMD ["mopidy", "--verbose"]
