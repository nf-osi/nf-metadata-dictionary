FROM ghcr.io/nf-osi/nfportalutils:develop

WORKDIR /app

RUN apt-get -yq install pandoc

RUN R -e "install.packages(c('rmarkdown', 'reactable', 'visNetwork'), repos='http://cran.rstudio.com/')"

ENTRYPOINT ["/bin/bash", "R", "-e", "rmarkdown::render('docs/index.Rmd')"]
