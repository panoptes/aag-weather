ARG image_url=gcr.io/panoptes-exp/panoptes-utils
ARG image_tag=develop
FROM ${image_url}:${image_tag} AS pocs-base

LABEL description="PANOPTES AAG Weather Service"
LABEL maintainers="developers@projectpanoptes.org"
LABEL repo="github.com/panoptes/aag-weather"

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

ARG userid=1000
ENV USERID $userid

ARG app_dir=/app
ENV APP_DIR $app_dir

WORKDIR "${APP_DIR}"
USER "${userid}"

# Update conda environment with dependencies.
COPY docker/environment.yaml .
RUN /conda/bin/conda env update -n base -f environment.yaml

ARG pip_install_name="."
ARG pip_install_extras=""

COPY --chown="${userid}:${userid}" . .
RUN echo "Installing ${pip_install_name} module with ${pip_install_extras}" && \
    /conda/bin/pip install --no-cache-dir "${pip_install_name}${pip_install_extras}" && \
    # Cleanup
    /conda/bin/pip cache purge && \
    /conda/bin/conda clean -tipsy && \
    sudo apt-get autoremove --purge --yes \
        gcc pkg-config && \
    sudo apt-get autoclean --yes && \
    sudo apt-get --yes clean && \
    sudo rm -rf /var/lib/apt/lists/*

CMD ["python /app/scripts/read-aag.py --config-file /app/config.yaml"]
