# boxhead


## Coding

### Style

Docstrings are formatted according to the [Google Style Guide](https://google.github.io/styleguide/pyguide.html).

All other formatting tries to adhere to [PEP8](https://www.python.org/dev/peps/pep-0008/) and is enforced by [YAPF](https://github.com/google/yapf/).

Code should be checked by [pylint](pylint.org) and [mypy](mypy-lang.org).

### Setup

```sh
git clone git@github.com:randomchars42/boxhead.git

cd boxhead

# setup a virtual environment with set python version
# set the version to >= 3.9
python -m venv -p python3.9 venv

chmod +x venv/bin/activate

# activate venv
. venv/bin/activate

# upgrade pip
pip install -U pip
# install tools
pip install mypy pylint yapf
```
