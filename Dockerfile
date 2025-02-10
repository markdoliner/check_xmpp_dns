# These steps are loosely ordered from "rarely changes" to "frequently changes" to take advantage
# of Docker build caching, so that builds during the development process are as fast as possible.

FROM python:3.13-alpine

WORKDIR /app

# Create a user for running the application, to avoid running as root.
RUN ["addgroup", "--system", "check-xmpp-dns"]
RUN ["adduser", "--disabled-password", "--home", "/app", "--ingroup", "check-xmpp-dns", "--no-create-home", "--shell", "/bin/false", "--system", "check-xmpp-dns"]

# Create a directory for the application to write logs to.
# The "install" command is used to create the directory with the desired ownership using a single
# command, to avoid having to run two commands (mkdir+chown).
RUN ["install", "-o", "check-xmpp-dns", "-g", "check-xmpp-dns", "-d", "/var/log/check-xmpp-dns"]

# Install poetry.
# The version is pinned as a best practice. It should be bumped regularly.
RUN ["pip", "install", "poetry==2.0.1"]

# Copy the minimum files needed to install dependencies.
# This is done at an early Docker layer so they don't need to be reinstalled each time the
# check-xmpp-dns source changes. chmod is used to remove write access.
COPY --chmod=444 poetry.lock pyproject.toml .

# Configure poetry to put the virtual environment in the local directory (/app).
# This is important because dependencies are installed as root but the app is run as a non-root
# user, so without this poetry would look for the virtual environment in a different location.
ENV POETRY_VIRTUALENVS_IN_PROJECT=true

# Configure poetry not to install pip in the virtualenv that it creates. It's not needed.
ENV POETRY_VIRTUALENVS_OPTIONS_NO_PIP=true

# Install dependencies.
RUN ["poetry", "install", "--compile", "--no-ansi", "--no-cache", "--no-directory", "--no-interaction", "--no-root", "--only=main"]

# Copy application files.
# chmod is used to remove write access.
COPY --chmod=444 templates templates
COPY --chmod=555 check_xmpp_dns.py .

# Compile Python files for faster execution.
RUN ["python", "-m", "compileall", "check_xmpp_dns.py"]

USER check-xmpp-dns
EXPOSE 8000

# ENTRYPOINT specifies the command+args that are appropriate always.
# port is specified even though 8000 is the default so that the behavior of this container doesn't
# change if the default value is changed in Uvicorn.
ENTRYPOINT ["poetry", "run", "uvicorn", "--factory", "--host=0.0.0.0", "--port=8000", "check_xmpp_dns:application"]

# CMD specifies reasonable default args that someone might conceivably want to change.
CMD ["--no-server-header", "--root-path=/check_xmpp_dns"]
