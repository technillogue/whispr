![checks](https://github.com/technillogue/whispr/workflows/checks/badge.svg)
[![codecov](https://codecov.io/gh/technillogue/whispr/branch/main/graph/badge.svg?token=bjcvyeVTsL)](https://codecov.io/gh/technillogue/whispr) [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) 

# whispr

a signal bot that runs a little social media. use commands to follow other users or invite them to follow you. messages to whisprbot that don't start with `/` are posts, and will be sent to your followers. unlike a group chat, your followers cannot see who else follows you, and have fine-grained control over who to get messages from. use `/help` for on-line documentation.


## installation 

whispr now uses a patched version of signal-cli that uses stdin/stdout instead of dbus. 
to run a server yourself, you must install [signal-cli](https://github.com/AsamK/signal-cli).

```sh
wget https://github.com/technillogue/signal-cli/blob/master/build/distributions/signal-cli-0.6.11.tar
tar xf signal-cli-0.6.11.tar 
ln -s signal-cli-0.6.11.tar/bin/signal-cli signal-cli-script
```

you need a phone number that is not already registered with signal. you can use google voice or twilio for this. all phone numbers must start with a plus sign and the country code.

```sh
export USERNAME="your phone number"
./signal-cli-script -u ${USERNAME} register
./signal-cli-script -u ${USERNAME} verify <verification code from signal>
sed 's/\+15345444555/${USERNAME}/' wispr.py
```

run `poetry install` (and `pip3 install poetry` if you haven't already)
