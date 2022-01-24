# boxhead


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

Logging uses a wrapper (`boxhead.boxheadlogging`) around the `logging` module to cover logging from multiple processes.

Import a logger using:

```python
from boxhead.boxheadlogging import boxheadlogging

logger: boxheadlogging.BoxHeadLogger = boxheadlogging.get_logger(__name__)

# your code here
```

## Setup

### Requirements

* `Python >= 3.9` as it uses typehinting only available beginning with 3.9.

#### Semi-optional:

* `libgpiod` with `python3-libgpiod` if you plan to use the `inputgpiod`-plugin. Alternatively you may implement the functionality using `RPi.GPIO` or any library of your choice.

#### Recommendations

* `pipenv` to create a virtualenvironment with a defined python version

  ```sh
  pip3 install pipenv
  ```

### Example setup using pipenv

```sh
git clone git@github.com:randomchars42/boxhead.git

cd boxhead

# setup a virtual environment with set python version
# set the version to >= 3.9
pipenv --python 3.9


# activate venv
pipenv shell

```
