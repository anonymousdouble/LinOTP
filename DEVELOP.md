# HOWTO: LinOTP Server Development Setup

This document guides you through the process of setting up a
development environment for LinOTP. In the end you should have a
running LinOTP system that you can easily modify and test.

The steps in a nutshell:

1. Get the LinOTP source code
2. Set up your LinOTP development environment
3. Configure LinOTP
4. Run the LinOTP development server
5. Run unit, functional and integration tests
6. Use MyPy for typechecking
7. Use pre-commit hooks for consistent formatting
8. Build the LinOTP debian package


## Get the LinOTP source code


Obtain the LinOTP source code from [LinOTP
GitHub](https://github.com/LinOTP/LinOTP "LinOTP on GitHub"):
```terminal
$ git clone https://github.com/LinOTP/LinOTP.git
```

## Set up your LinOTP development environment

If you want to develop LinOTP, you first need to install some software
packages that LinOTP depends upon.

On a Debian-based system, run as a superuser:
```terminal
$ apt-get install build-essential python3-dev \
                python3-mysqldb mariadb-server libmariadb-dev-compat libmariadb-dev \
                libldap2-dev libsasl2-dev \
                libssl-dev
```

On macOS, install the following dependencies to run LinOTP natively
and build LinOTP via containers:
```terminal
$ brew install libsodium coreutils
```

LinOTP can use a variety of SQL databases but MySQL/MariaDB is most
widely used. Other options include PostgreSQL and SQLite, although
SQLite is not recommended for production setups.

The `libldap2-dev` and `libsasl2-dev` system packages are needed when
installing the `python-ldap` dependency via `pip`. Similarly, the
`libssl-dev` package is needed when installing the `cryptography`
dependency via `pip`.

A “virtual environment” lets you install additional packages locally
(without administrator privileges) using Python's `pip` tool. It also
prevents the pollution of your host system with non-distribution
packages. We strongly recommend installing a virtual environment as
follows:
```terminal
$ python3 -m venv linotp_dev       # Pick a name but be consistent
$ source linotp_dev/bin/activate
```
Then, install the development dependencies:
```terminal
$ pip3 install -e .
```
In order to run automated tests you must also install the test dependencies:
```terminal
$ pip3 install -e ".[test]"
```

For a quickstart using the default configuration, run:
```terminal
$ mkdir -p linotp/cache linotp/data linotp/logs
$ linotp init database
$ linotp init audit-keys
$ linotp init enc-key
$ linotp local-admins add <your_username>
$ linotp local-admins password --password <your_password> <your_username>
$ linotp run
```

The last command starts a development server. Now you can open the LinOTP
management interface in your browser (`http://localhost:5000/manage/`) and
login as `<your_username>`.

All available CLI commands have their own documentation, and you can find them
listed in the top level man page **linotp(1)**. Should you not yet have
installed the linotp man pages, you can also reference them by path, like this:
```terminal
 $ man ./man/man1/linotp.1
```

`init database` will create a SQLite database by default. If you want to use a
PostgreSQL or MariaDB database instead, you can override that setting through
the following environment variable before running `linotp init database`:
```terminal
 $ export LINOTP_DATABASE_URI="postgres://user:pass@host/db_name"
```
or
```terminal
 $ export LINOTP_DATABASE_URI="mysql+pymysql://user:pass@host/db_name"
```
Alternatively you can also set this variable in a LinOTP configuration file, as
we explain next.

## Configure LinOTP

LinOTP provides three configuration presets for development, testing and
production, but you can customize any of the configuration entries by
overriding environment variables or specifying additional configuration files.

To inspect the configuration of your LinOTP instance, run `linotp config show`,
or `linotp config explain` if you need more information on the configuration
entries. Both commands accept additional parameters, which you can look up in
**linotp-config(1)**.

### Configuration presets

Configuration settings are hard-coded in `linotp/settings.py`, which also
defines a small set of "environments" that pre-cook basic configurations:

- _development_ is aimed at LinOTP developers running LinOTP on their
  local machine. It enables debugging (including copious log messages,
  auto-reload if source code files change, and the interactive Flask
  debugger) and defaults to using a local SQLite database. *This is
  not safe to use in a production setting.*
- _testing_ is an environment that facilitates running system
  tests. Like _development_, it enables more prolific logging output.
- _production_ is a more streamlined and secure setup to be used on
  productive servers.

One of these environments can be selected by setting the `FLASK_ENV`
variable to `development`, `testing`, or `production`. If unset, it
defaults to `default`, which is identical to `development`.

### Customizing the configuration

Additional configuration settings can be made in configuration
files. LinOTP looks at the configuration files listed in the
`LINOTP_CFG` environment variable, whose value consists of a list of
one or more file names separated by colons. For example,

    LINOTP_CFG=/usr/share/linotp/linotp.cfg:/etc/linotp/linotp.cfg

would read first the `/usr/share/linotp/linotp.cfg` file and then the
`/etc/linotp/linotp.cfg` file. 

Later configuration settings override earlier ones, and settings in
configuration files override hard-coded default settings in `settings.py`.

Relative file names in `LINOTP_CFG` are interpreted relative to Flask's
`app.root_path`, which by default points to the `linotp` directory of the
LinOTP software distribution (where the `app.py` file is). If `LINOTP_CFG` is
undefined and is not started from a packaged version, it defaults to
`linotp.cfg`.

The advantage of this approach is that it allows a clean separation between
configuration settings provided by a distribution-specific LinOTP package and
configuration settings made by the local system administrator, which would each
go into separate files. If the package-provided file is changed or updated in a
future version of the package, the local settings will remain untouched.

#### Format of configuration entries

LinOTP's configuration files are Python code, so you can do whatever
you can do in a Python program, although it is probably best to
exercise some restraint. (As a somewhat contrived example, you could
use the Python `requests` package to download configuration settings
from a remote HTTP server. But please don't actually do this unless
you understand the security implications.)

In the simplest case, configuration settings look like assignments to
Python variables whose names consist strictly of uppercase letters,
digits, and underscores, as in

	LOG_FILE_DIR = "/var/log/linotp"

(Variables with lowercase letters in their names are ignored when a
configuration file is scoured for settings, so you could use them as
scratch variables.) We say "look like" because we actually apply data
type conversions if necessary to accommodate non-string configuration
settings like `LOG_FILE_MAX_LENGTH` (which is internally a Python
`int`), and we perform rudimentary plausibility checks to ensure that
the value of configuration settings make basic sense (for example, you
will not be allowed to set `LOG_FILE_MAX_LENGTH` to a negative value).

As a special feature, configuration settings whose names end in `_DIR`
or `_FILE` are supposed to contain the names of directories or files
(surprise!). These can either be absolute names (starting with a `/`)
or else will have the value of the `ROOT_DIR` variable prepended when
they are used. This means that if the very last configuration setting
you make changes `ROOT_DIR`, the value assigned there will be the
effective one even for other earlier settings that use relative path
names: After

    ROOT_DIR = "/var/foo"
	LOG_FILE_DIR = "linotp"
	ROOT_DIR = "/var/bar"

the effective value of `LOG_FILE_DIR` will be `/var/bar/./linotp`. (Note
that we're inserting a `/./` to mark where the implicit value of
`ROOT_DIR` stops and the configured value of the setting starts.) The
only exception to this is `ROOT_DIR` itself, which must always contain
an absolute directory name, and defaults to Flask's `app.root_path`
unless it is explicitly set in a configuration file.

Finally, hard-coded configuration defaults as well as settings in
configuration files can be overridden from the process environment. If
a configuration setting inside LinOTP is named `XYZ`, then if a
variable named `LINOTP_XYZ` is defined inside the environment of the
LinOTP process, its value will be used to set `XYZ`. This is helpful
in Docker-like setups where configuration files are inconvenient to
use.

Note that this only works for LinOTP configuration settings that are
mentioned in `settings.py` (Flask has a bunch of its own configuration
settings that aren't strictly part of the LinOTP configuration but can
be set in LinOTP configuration files).

Some configuration settings are supposed to contain non-string data
such as integers or lists, and LinOTP tries to convert the (string)
values of environment variables appropriately. For example, the value
of `LINOTP_LOG_FILE_MAX_LENGTH` will be converted to an integer to set
the `LOG_FILE_MAX_LENGTH` configuration setting, and you may wish to
amuse yourself by investigating what happens to the value of
`LINOTP_LOGGING`.

### Predefined directory names

LinOTP predefines certain directory names that should be adapted to
the conventions of a specific Linux distribution when preparing a
LinOTP distribution package for that distribution. These include:

- `ROOT_DIR`: The “root directory” of the LinOTP configuration file
  tree. By default this is the “Flask application root directory”,
  `app.root_path`, IOW the directory where LinOTP's `app.py` file is
  located. As mentioned above, the value of `ROOT_DIR` is prepended to
  the values of other configuration settings for files and directories
  if these are relative path names. A distribution will set this to
  something more useful such as `/etc/linotp`.

- `CACHE_DIR`: This directory is used for temporary storage of LinOTP
  data. It defaults to `ROOT_DIR/cache`, but in a distribution will
  more likely be something like `/var/cache/linotp`. Note that the
  actual caches are supposed to be in subdirectories of this directory
  in order to avoid namespace issues. For example, the resolver cache
  is found in `CACHE_DIR/resolvers`, and if Beaker is used with a
  file-backed cache (not the default method), that cache will be in
  `CACHE_DIR/beaker`. These assignments cannot be changed except by
  changing the LinOTP source code.

- `DATA_DIR`: Short-lived temporary data can be stored in
  subdirectories of this directory. It defaults to `ROOT_DIR/data` but
  in a distribution wil probably end up as `/run/linotp`. Currently
  this is only used to cache Mako templates that have been compiled to
  Python, in the `template-cache` subdirectory. Again, this can only
  be changed by editing the LinOTP source code.

  Note that while the other directories can usually be created when
  LinOTP is installed, the volatile nature of `/run` on most systems
  can make it necessary to recreate `DATA_DIR` at odd times (e.g.,
  after a system reboot). Since making new directories in `/run`
  usually requires root privileges, LinOTP will generally not be a in
  a position to do it by itself (or shouldn't be in such a position in
  any case). A good approach to use instead is systemd's `tmpfiles`
  mechanism. Installs that do not use systemd (such as Docker-based
  installs) need to ensure that the directory is created by some other
  means.

- `LOG_FILE_DIR`: This is where the log file ends up if you're logging
  to a file (which is something LinOTP does by default). By default
  this is `ROOT_DIR/logs` but distribution packages will probably wish
  to use something like `/var/log/linotp`.

If you're making a distribution package, don't edit LinOTP's
`settings.py` file to adapt the values of these directories. Instead,
make a new configuration file and put it in a reasonable place such as
`/usr/share/linotp/linotp.cfg`. A suitable defaults file for Debian
based distributions is available at `config/linotp.cfg`. The default
configuration path can be set by placing a file with the name
`linotp-cfg-default` in the same directory as the main `app.py`. The
configuration path for Debian can be found in the file
`config/linotp-cfg-default`.

## Run the LinOTP development server

To run LinOTP for development, execute Flask from the LinOTP source
directory (`linotpd/src`) as follows:
```terminal
$ FLASK_APP=linotp.app flask run
```
This starts the Flask development server. Unless you specify otherwise
using the `--host` and `--port` options, the development server will
bind to TCP port 5000 on the loopback address (127.0.0.1).

The development server is fine for local experiments but should *under
no circumstances* be used to run LinOTP in a production
environment. The officially approved method for running LinOTP
productively uses Apache and `mod_wsgi`, and the details of this are
beyond the scope of this document. Refer to the content of the LinOTP
source directory's `config` subdirectory for inspiration, or –
preferably – check the [LinOTP Installation
Guide](http://www.linotp.org/doc/latest/part-installation/index.html).

To make life easier, LinOTP offers a `linotp` command which you can
run anywhere without having to define `FLASK_APP`. To enable this on
your development system, go to the LinOTP source directory and execute
the
```terminal
$ python3 setup.py develop
```
command. (This installs the `linotp` command in the virtualenv's `bin`
directory.) Giving the `make develop` command in the top-level
directory should also do the trick. After this, a simple
```terminal
$ linotp run
```
will launch the Flask development server. (You can still use
`FLASK_ENV` to specify the desired environment.)

Make sure to create an admin user, otherwise you will not be able to log in to
LinOTP's management interface:
```
$ linotp local-admins add <your_username>
$ linotp local-admins password -p <your_password> <your_username>
```

## Run unit, functional, and integration tests

### Unit and functional tests

You can run unit and functional tests by entering the respective
commands below from the top-level directory of the LinOTP distribution:
```terminal
$ make test               # will run all tests
$ make unittests          # will run only unit tests
$ make functionaltests    # will run only functional tests
$ make integrationtests   # will run only integration tests
```
You can also run the tests directly in their directories:
```terminal
$ pytest linotpd/src/linotp/tests/unit
```
or
```terminal
$ pytest linotpd/src/linotp/tests/functional
```
If you want to run only the tests in a single file, invoke `pytest`
with the path to that file.

When using `make`, you can pass command-line arguments to `pytest` by
assigning them to `PYTESTARGS`:
```terminal
$ make unittests PYTESTARGS="-vv"
```
See the [Pytest documentation](https://docs.pytest.org/) for more
information about using pytest.

### Integration tests

To run integration tests with Selenium, please make sure that your
system has the `chromedriver` executable installed.

Then start a LinOTP development server and edit
`linotpd/src/linotp/tests/integration/server_cfg.ini` so that the
`[linotp]` section contains its hostname/IP address and port number.

You can now execute integration tests with:
```terminal
$ pytest --tc-file=linotpd/src/linotp/tests/integration/server_cfg.ini <path_to_test_file>
```
You can find sample test files under `linotpd/src/linotp/tests/integration`.


## Use MyPy for typechecking

To run a type check on the source code, install `mypy` and `sqlalchemy-stubs`.
Both requirements are part of the develop requirements:
```terminal
$ pip3 install -e ".[develop]"
```
Then run `mypy` on a directory of your choice like
```terminal
$ mypy some/python/dir
```
If you do not wish to be shown type errors from imported modules, use
the `--follow-imports=silent` flag.

The `--show-column-numbers` flag can also be helpful when looking for
the exact location of a problem.


## pre-commit hooks for consistent formatting

This repository is using the [pre-commit](https://pre-commit.com/) framework
to ensure a consistent style across the whole project. Inspect
[.pre-commit-config.yaml](.pre-commit-config.yaml) for the configured tools and our [pyproject.toml](pyproject.toml)
file for the configuration.

Install `pre-commit` manually via pip or as part of our develop dependencies:
```terminal
$ pip3 install -e ".[develop]"
```
Then install the pre-commit hook in git so that it runs before a commit to
ensure correct formatting. The same hook is tested in CI, so we strongly
advise to install the hook, even if you use all of the tools in your IDE.
This way, you will never push a commit that fails the pre-check. 
```terminal
$ pre-commit install
```

You can also run the pre-commit hook manually`:
```terminal
$ pre-commit run
```
Use the arguments `--files …` or `--all-files` to change what files are checked.


## api documentation / api-docs


First install the requirements to generate the api documentation:
```terminal
$ pip3 install -e ".[apidocs]"
```

However, this is not necessary if you have already installed the requirements
for the development (".[develop]") environment.

To build the api documentation enter the following commands in your terminal:

```terminal
$ cd api-doc
$make apidocs html
```x

## Debian packages

You can generate a LinOTP `.deb` package that is suitable for
installation on a Debian GNU/Linux system using the
```terminal
$ make builddeb
```
command from the top-level directory. This uses Debian packaging tools
and therefore works best if you do it on a machine that is running
Debian GNU/Linux. See below for building Debian packages inside a Docker
container.

The
```terminal
$ make deb-install
```
command will build a Debian package and place it in the `build`
subdirectory of the top-level directory. You can specify a different
directory by passing it to `make` as the value of the `DESTDIR`
variable.


### Using Docker to build the Debian package

You can use the `Makefile` provided by the LinOTP distribution to
build various Docker container images that help with LinOTP
development:

- A `linotp-builder` image includes everything that is necessary to
  build LinOTP packages. This will use the `buster` version of Debian
  GNU/Linux (the current stable version at the time of this writing),
  no matter what flavour of Linux your machine is running.

- A `linotp` image contains a ready-to-run LinOTP inside an Apache web
  server.

- A `linotp-unit` image contains a LinOTP setup that will run LinOTP
  unit tests. It is based on the `linotp` image but contains
  additional dependencies for the testing environment.

- A `selenium-test` image contains a LinOTP setup that will run LinOTP
  integration tests using Selenium in a different image.

All of these can be conveniently built and run using targets in the
`Makefile` in the top-level directory:

- `make docker-linotp` will build LinOTP in a `linotp-builder`
  container, extract the `.deb` file and place it in the `build`
  subdirectory of the top-level directory.

- `make docker-unit` and `make docker-functional` build LinOTP and run
  unit tests and functional tests in their respective containers. Some
  functional tests take a very long time and are therefore only run
  once per night in our CI/CD environment; these can be enabled by
  passing the `NIGHTLY=yes` variable to `make`.

- `make docker-selenium` will build LinOTP and run Selenium-based
  integration tests in a containerised environment.

- `make docker-build-all` will build all container images.

- `make docker-pylint` will run static source code checks on a LinOTP
  test image.

Refer to the `Makefile` for details of how these targets interact, and
for additional configuration parameters.

## Gitlab-CI Pipelines

### Failing *-test-pypi Jobs

If *-test-pypi jobs fail with
```terminal
WARNING: Failed to pull image with policy "if-not-present": [...] not found: manifest unknown: manifest unknown
```
please run the job `build-and-upload-pypi-image-testenv` and retry failed tests after the docker image was pushed.

This will be the case when your merge request targets a non-protected branch; e.g. a merge request to another merge request branch.