# plapperkasten

Manage a headless media device.

## What?!

Turn a Raspberry Pi with only buttons and speakers attached into a jukebox playing local music.

In a typical setup you might have a couple of buttons wired to a raspberry pi's GPIO pins, some speakers attached to the audio jack and a RFID reader plugged into one of the USB ports.

This is based on the idea of the [PhonieBox](https://www.phoniebox.de) (["original" software](https://github.com/MiczFlor/RPi-Jukebox-RFID), more information on [awesomeopensource.com](https://awesomeopensource.com/project/MiczFlor/RPi-Jukebox-RFID)) but written from scratch and not as feature-rich - yet!

`plapperkasten` has started as a small script to learn the workings of a Raspberry Pi box and to avoid the great but intimidatingly complex [RPi-Jukebox-RFID](https://github.com/MiczFlor/RPi-Jukebox-RFID).  As the project has grown more complex and mature I've decided to release it into the wild - so here it is.

## Features

  * **Easy setup**: install the python package from [PyPi](https://pypi.org/project/plapperkasten/) (with `pip install plapperkasten`) or configure the whole machine using [plapperkasten-setup](https://github.com/randomchars42/plapperkasten-setup). This will guide you from the download of the OS all the way to a functioning device including `SSH`, setting up an isolated python environment, configuring sound, users, etc.
  * **Nearly everything is a plugin**: Theres a plugin for controlling the sound using `ALSA` and one for `PipeWire`. Need to output to `JACK` or `PulseAudio`? [Write your own plugin by lending from the existing plugins](#creating-a-plugin).
  * **Completely written in Python 3**:
  * **Does not run as a super user**: `plapperkasten` is geared towards interacting with hardware buttons, sound and the like without needing special privileges. This needs some configuration of your OS but [plapperkasten-setup](https://github.com/randomchars42/plapperkasten-setup) is there to help you - or if you want it your way to give you some hints.

## Setup

Please see <https://github.com/randomchars42/plapperkasten-setup> for detailed instructions and an easy installer.

## Development

### Style

Docstrings are formatted according to the [Google Style Guide](https://google.github.io/styleguide/pyguide.html).

All other formatting tries to adhere to [PEP8](https://www.python.org/dev/peps/pep-0008/) and is enforced by [YAPF](https://github.com/google/yapf/).

Log entries use lazy evaluation, i.e., `logger.debug('start %s', name)`, start with a lower-case letter and do not end with a full stop.

Raised errors on the other hand use f-strings (if necessary) and contain whole sentences, i.e. `ValueError(f'{variable} did not match XXXX.')`.

### Linting / Checking

Code should be checked by [pylint](pylint.org) and [mypy](mypy-lang.org).

### Paths

All path representations should be `pathlib.Path`-objects instead of strings.

### Logging

Logging uses a wrapper (`plapperkasten.plklogging`) around the `logging` module to cover logging from multiple processes.

Import a logger using:

```python
from plapperkasten.plklogging import plklogging

logger: plklogging.PlkLogger = plklogging.get_logger(__name__)

# your code here
```

### Setup for development

#### Requirements

* `Python >= 3.10` as it uses typehinting features only available beginning with 3.10.

#### Semi-optional

* `libgpiod` with `python3-libgpiod` and `gpiodmonitor>=1.1.3` if you plan to use the `inputgpiod`-plugin. Alternatively you may implement the functionality using `RPi.GPIO` or any library of your choice - but beware: you're gooing to need super user privileges!

#### Recommendations

* [pyenv](https://github.com/pyenv/pyenv) to setup a python version withput messing up your system.

* [pipenv](https://pipenv.pypa.io/en/latest/index.html) to create a virtual environment with a defined python version.

#### Example setup using pipenv

```sh
git clone git@github.com:randomchars42/plapperkasten.git

cd plapperkasten

# consider adding this to your .bashrc / equivalent for your shell:
# `export PIPENV_VENV_IN_PROJECT=1`
# this leads to a folder `.venv` being created at the project root
# otherwise you might need to tweak the `[tool.mypy]`` path in
# `pyproject.toml` (depending on your editor setup).

# setup a virtual environment with set python version
# set the version to >= 3.10
pipenv --python 3.10

# install development dependencies
pipenv install --dev

# activate venv
pipenv shell
```

### Plapperkasten logic in a nutshell

`plapperkasten` is a simple platform for plugins that can talk to each other to control a jukebox. There is a plugin recieving input from buttons (`src/plapperkasten/plugins/inputgpiod`), one recieving input from RFID readers (`src/plapperkasten/plugins/inputdevinputevent`), one for controlling an MPD client (`src/plapperkasten/plugins/mpdclient`) and so forth.

A good place to get to know the overall logic is `src/plapperkasten/plapperkasten.py`. This is the main entry point into the programme.

It will in turn:

  * start a process for logging
  * load the configuration files
  * gather all plugins from `src/plapperkasten/plugins` and `~/.config/plapperkasten/plugins` (or wherever `~/.config/plapperkasten/config.yaml` points it to)
  * start a process for each plugin (that is not blacklisted in `~/.config/plapperkasten/config.yaml`)
  * the plugins register for events they might process
  * trigger `on_before_run()` for each pluggin
  * wait for the plugins to send events to process, translate or re-emit so that other plugins can react to them
  * or wait for all plugins to exit (either by themselves or because of a `terminate` event)
  * if a `shutdown` event has been emitted, `plapperkasten` will try to shutdown the host ([here's how to stop it during development](#preventing-shutdown-during-development))

### Examplary flow of events

In a typical setup you might have a couple of buttons wired to a raspberry pi's GPIO pins, some speakers attached to the audio jack and a RFID reader plugged into one of the USB ports.

#### An RFID token has been recognised

  * `inputdevinputevent` listens to the attached RFID reader and reads a token.
  * `inputdevinputevent` sends an `raw` event with the payload `0123456789` (the value read from the token) to `plapperkasten` via its pipe
  * `plapperkasten` recieves the event, looks it up in `~/.config/plapperkasten/events.map` and sees it maps to a `load_source` event with the payload `use=Mpdclient`, `key=Music/Folder/Band/Album`.
  * `plapperkasten` emits `load_source` to those who listen
  * `mpdclient` listens to `load_source` and makes mpd or mopidy (whichever you run on the system) add the folder `Music/Folder/Band/Album` to a new playlist and start playing it

#### A button is pressed

  * `inputgpiod` listens to the gpio pins and recieves a signal from pin 12.
  * `inputgpiod` sends an event `12_short` to `plapperkasten` via its pipe
  * `plapperkasten` recieves the event, looks it up in `~/.config/plapperkasten/events.map` and sees it maps to a `volume_increase` event
  * `plapperkasten` emits `volume_increase` to those who listen
  * `pwwp` (short for PipeWire / Wireplumber) listens to `volume_increase` and calls `wpctl set-volume @DEFAULT_AUDIO_SINK@ 1%+`
  * `pwwp` sends an event `beep` to `plapperkasten`
  * `plapperkasten` knows from its config that it should pass those events through, so it re-emits the event to whom it may concern
  * `soundeffects` listens to the `beep` and produces a beep

### Core files

  * `src/plapperkasten/settings/config.yaml` contains default settings - user changes should not go here
  * `~/.config/plapperkasten/config.yaml` may contain any of the settings from `src/plapperkasten/settings/config.yaml` and overwrite them
  * `src/plapperkasten/settings/events.map` could contain default event mappings but is empty - user changes should not go here
  * `~/.config/plapperkasten/events.map` may contain events defined by the user (see `src/plapperkasten/keymap.py` for a description of the form)

### Creating a plugin

A good place to start is to copy the "example" plugin and to take off from there. You will find it in `src/plugins/example`.

Each plugin lives in its own process. This has some severe implications:

  * You need to use the logging functionality provided by `plapperkasten.plklogging` [see logging above](#logging).
  * The class is initialised in the main process, this is where it might access data from the configuration or other parts of the programme. It may only store immutable information or fresh copies (as returned by `plapperkasten.config`) or else the multiprocessing hell will be upon you.
  * If you need to do something (like fetching configuration values or registering for events) on initialisation before the plugin's process was started use `on_init`.
  * If you need to do something as soon as the new process has started use `on_before_run`.
  * If you need to do something every *X* seconds use `on_tick` and set `self._tick_interval` to *X* in `on_init`.
  * If you need to respond to an event, register for it and write an `on_EVENT` method, e.g., place `register_for('my_event')` in `on_init` and write `on_my_event` to handle the event.
  * If you need total controll - you usually don't - overwrite `run`, as in `src/plapperkasten/plugins/inputgpiod/inputgpiod.py`.
  * If you need to tidy up after you put the code in `on_after_run`.
  * If you want to prevent `plapperkasten` from shutting down after a period of idleness use `send_busy`.
  * If you want `plapperkasten` to think it might restart its "idle" countdown use `send_idle` (but the countdown will only commence if all plugins are idle).
  * If you want to send an event to `plapperkasten` use `send_to_main`.

### Preventing shutdown during development

To avoid shutdown during development set `debug` in `~/.config/plapperkasten/config.yaml` to `true`.
