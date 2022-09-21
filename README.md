# plapperkasten

## Coding

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

## Setup as an isolated app integrated into the system (e.g. on a remote box)

Please see <https://github.com/randomchars42/plapperkasten-setup> for detailed instructions and an easy installer.

## Setup for development

### Requirements

* `Python >= 3.9` as it uses typehinting only available beginning with 3.9.

#### Semi-optional:

* `libgpiod` with `python3-libgpiod` and `gpiodmonitor>=1.0.0` if you plan to use the `inputgpiod`-plugin. Alternatively you may implement the functionality using `RPi.GPIO` or any library of your choice.

#### Recommendations

* `pipenv` to create a virtual environment with a defined python version

  ```sh
  pip3 install pipenv
  ```

### Example setup using pipenv

```sh
git clone git@github.com:randomchars42/plapperkasten.git

cd plapperkasten

# consider adding this to your .bashrc / equivalent for your shell:
# `export PIPENV_VENV_IN_PROJECT=1`
# this leads to a folder `.venv` being created at the project root
# otherwise you might need to tweak the `[tool.mypy]`` path in
# `pyproject.toml` (depending on your editor setup).

# setup a virtual environment with set python version
# set the version to >= 3.9
pipenv --python 3.9

# install development dependencies
pipenv install --dev

# activate venv
pipenv shell
```
