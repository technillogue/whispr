![checks](https://github.com/technillogue/whispr/workflows/checks/badge.svg)
[![codecov](https://codecov.io/gh/technillogue/whispr/branch/main/graph/badge.svg?token=bjcvyeVTsL)](https://codecov.io/gh/technillogue/whispr) [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) 

# whispr

a signal bot that runs a little social media. use commands to follow other users or invite them to follow you. messages to whisprbot that don't start with `/` are posts, and will be sent to your followers. unlike a group chat, your followers cannot see who else follows you, and have fine-grained control over who to get messages from. use /help for on-line documentation.


## installation 

to run a server yourself, you must first install [signal-cli](https://github.com/AsamK/signal-cli).

```sh
export VERSION="0.6.11"
wget https://github.com/AsamK/signal-cli/releases/download/v"${VERSION}"/signal-cli-"${VERSION}".tar.gz
sudo tar xf signal-cli-"${VERSION}".tar.gz -C /opt
sudo ln -sf /opt/signal-cli-"${VERSION}"/bin/signal-cli /usr/local/bin/
```

you need a phone number that is not already registered with signal. you can use google voice or twilio for this. all phone numbers must start with a plus sign and the country code.

```sh
export USERNAME="your phone number"
signal-cli -u ${USERNAME} register
signal-cli -u ${USERNAME} verify <verification code from signal>
signal-cli -u ${USERNAME} daemon
```

most of the dependencies can be installed with `poetry install`, but [PyGObject](https://pygobject.readthedocs.io/en/latest/getting_started.html#ubuntu-logo-ubuntu-debian-logo-debian) must installed seperately

note that DBus requires systemd and X11 to work.


