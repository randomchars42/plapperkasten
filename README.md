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

### Web interface

The web server listens on port `8080`. Its `hostname` setting is the address
to bind on the device running Plapperkasten. For access from other devices on
your local network, add this to `~/.config/plapperkasten/config.yaml`:

```yaml
plugins:
  server:
    hostname: '0.0.0.0'
    port: 8080
```

Then open [http://plapperkasten1:8080](http://plapperkasten1:8080), or use the
Pi's current name or IP address. Keep `hostname: '127.0.0.1'` for access only
from the device itself. A hostname that resolves to another computer cannot
be used as the bind address.

If the configured address or hostname is not available during boot, the web
server retries once per second for up to 60 seconds while the network starts.

### Spotify playlists

The **Playlists** tab can play a pasted Spotify playlist link and save named
favorites. Saved playlists have **Play** and **Remove** buttons. Saving or
removing a favorite does not interrupt playback. Saving the same name again
updates its link. The existing player buttons, GPIO buttons and volume controls
work with the selected playback source, including Spotify.

Spotify playback uses [Spotify Soloist](https://developer.spotify.com/documentation/soloist),
which must run separately on the same Pi. Plapperkasten does not need your
Spotify API key, a Web API app, or an additional OAuth login.

1. Download Soloist for the Pi's architecture from the
   [official downloads page](https://developer.spotify.com/documentation/soloist/reference/downloads-and-updates)
   and make its `soloist` executable available on `PATH` (or configure its full
   path below). Each user needs Spotify Premium and their own
   [Soloist API key](https://developer.spotify.com/dashboard/soloist).
2. Start Soloist as the same Linux user that runs Plapperkasten and its PipeWire
   session, using a private environment variable containing the key:

   ```sh
   soloist --device-name "Plapperkasten" --api-key "$SOLOIST_API_KEY" --ws 127.0.0.1:9090
   ```

   In the Spotify app on the same network, select **Plapperkasten** once to
   pair it. Soloist keeps that session in its data directory for future starts.
   Confirm `soloist ctl status --ws 127.0.0.1:9090` reports a logged-in session.
   Soloist uses the default audio output; running in the same PipeWire session
   allows Plapperkasten's existing volume/output controls to apply.
3. Add this to `~/.config/plapperkasten/config.yaml`, merging it with any
   existing `plugins` section, then restart Plapperkasten:

   ```yaml
   plugins:
     spotify:
       enabled: true
       executable: 'soloist'  # or an absolute path to the executable
       endpoint: '127.0.0.1:9090'
   ```

4. Open the existing web interface, select **Playlists**, and paste a full
   `https://open.spotify.com/playlist/...` share link. Choose **Play on
   Plapperkasten**, or enter a name and choose **Save favorite**. Spotify URI
   values (`spotify:playlist:...`) also work. Short `spotify.link` URLs must
   first be opened in a browser to obtain their full playlist link.

Favorites are stored in `~/.config/plapperkasten/spotify_favorites.yaml` by
default. Set `plugins.spotify.filename_favorites` to change the filename; a
relative path is resolved against `core.paths.user_directory`. The file is a
YAML mapping of names to playlist URIs and may also be edited while the server
is running. Changes made in the browser survive service restarts.

The page reports Soloist's confirmed playback status, current track and
connection errors. Selecting a local playlist or scanning an MPD card pauses
Spotify and hands the controls back to MPD. Selecting Spotify stops MPD.
**Stop** pauses Spotify and resets the current track to its beginning. Playlist
positions are not stored separately for each favorite.

Keep Soloist's WebSocket listener on `127.0.0.1`; browsers use Plapperkasten's
HTTP server rather than connecting to Soloist directly. Keep the API key out of
the web page, favorites file and source repository. For unattended startup,
an example user service is provided in [examples/soloist.service](examples/soloist.service).
Put the key in a private `~/.config/soloist/soloist.env` file (mode `600`) as
`SOLOIST_API_KEY=your-key`, adjust the service's executable path, and install it
under `~/.config/systemd/user/`. Enable it with
`systemctl --user enable --now soloist.service`. Keep the same Soloist data
directory when switching from a manual run to the service, and stop the manual
process first.

Soloist builds expire after 90 days, so update the executable from Spotify
regularly and restart its service. The binary and API key are not distributed
with Plapperkasten. See Spotify's
[setup](https://developer.spotify.com/documentation/soloist) and
[CLI reference](https://developer.spotify.com/documentation/soloist/reference/soloist-ctl)
for installation, pairing and updates.

### Held volume buttons

The standard volume pins (13 and 24) repeat every 100 ms while held. Other
buttons keep the 300 ms repeat interval. Adjust `plugins.inputgpiod.press_pulse_intervals`
in your configuration if your volume buttons use different pins, or override
the values to change the repeat speed. For example:

```yaml
plugins:
  inputgpiod:
    press_pulse_intervals: {13: 0.1, 24: 0.1}
```

PipeWire volume steps use one capped `wpctl` command when supported; older
WirePlumber versions retain the read-and-set behavior. Feedback sounds are
coalesced during rapid input to avoid a backlog of delayed beeps.

### Bookworm and Trixie

The GPIO extra requires gpiodmonitor 1.4, which supports the distro libgpiod
1.x and 2.x bindings without changing button configuration. Use a fresh
virtual environment with `--system-site-packages` under the distro Python.
See [the setup instructions](https://github.com/randomchars42/plapperkasten-setup)
for selecting the matching WirePlumber volume configuration and power-off hook.

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

### Web controls and status

The web interface shows the last RFID card ID and whether auto shutdown is
active or paused. Status updates automatically every second. Card IDs retain
leading zeros, and unassigned cards are shown without triggering an action.
The last ID is kept in memory until the service restarts; selecting a playlist
in the web interface does not count as reading a card.

Use **Pause auto shutdown** to keep the box running while idle. The pause lasts
until **Resume auto shutdown** is pressed or the service restarts. Resuming
starts a fresh configured idle timeout once the box is idle. Manual shutdown
still works while auto shutdown is paused.

`GET /api/status` returns `last_rfid_card` (a string, or `null` before the first
read) and `autoshutdown_paused` (a boolean, or `null` until the auto shutdown
plugin reports its state). The built-in events `rfid_read`,
`autoshutdown_pause`, `autoshutdown_resume` and `autoshutdown_status` are routed
automatically, including with existing `core.events.passthrough` settings.

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
