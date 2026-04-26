FROM python:3-slim

ARG SNAPCAST_VERSION=0.35.0
ARG SNAPWEB_VERSION=0.9.3

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
    curl

RUN ARCH=$(dpkg --print-architecture) && \
    DEBIAN_CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME") && \
    curl -sSL -o /tmp/snapserver.deb "https://github.com/snapcast/snapcast/releases/download/v${SNAPCAST_VERSION}/snapserver_${SNAPCAST_VERSION}-1_${ARCH}_${DEBIAN_CODENAME}.deb" && \
    apt-get install -y --no-install-recommends /tmp/snapserver.deb && \
    curl -sSL -o /tmp/snapweb.deb "https://github.com/snapcast/snapweb/releases/download/v${SNAPWEB_VERSION}/snapweb_${SNAPWEB_VERSION}-1_all.deb" && \
    apt-get install -y --no-install-recommends /tmp/snapweb.deb

RUN apt-get purge -y curl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/snapserver.deb /tmp/snapweb.deb && \
    mkdir -p /var/lib/mopidy/media /audio && \
    mkfifo /audio/snapfifo

RUN pip install --no-cache-dir mopidy-mpd

COPY . /src/mopidy-mp3quran
RUN pip install --no-cache-dir /src/mopidy-mp3quran && \
    rm -rf /src/mopidy-mp3quran

COPY docker/snapserver.conf /etc/snapserver.conf
COPY docker/mopidy.conf /etc/mopidy/mopidy.conf

EXPOSE 6600 6680 1704 1705 1780

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["mopidy", "--verbose"]
