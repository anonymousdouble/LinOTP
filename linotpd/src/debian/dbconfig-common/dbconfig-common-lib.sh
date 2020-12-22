# This file contains various functions used by the database scripts

# Load the library as follows:
# . /usr/share/dbconfig-common/scripts/linotp/lib.sh

# Load dbconfig-common configuration
. /etc/dbconfig-common/linotp.conf

LINOTP_CONFIG_FILE=/etc/linotp/conf.d/01-debian-database.cfg
LINOTP_USER=linotp

msg="LinOTP: "

echo_prio() {
  t=$(date +"%Y/%m/%d - %T")
  echo >&2 "$t $1 [linotp postinst] $2"
}
echo_info() {
  echo_prio INFO "$1"
}
echo_warn() {
  echo_prio WARNING "$1"
}
echo_error() {
  echo_prio ERROR "$1"
}
echo_log() {
  echo >&2 "${msg}$1"
}

# escape_login
#
# Prints the RFC 1738 escaped value of
# dbconfig-common user + optional password
#
escape_login() {
  export dbc_dbuser dbc_dbpass
  python3 -c '
from urllib.parse import quote_plus
import os

user = os.environ["dbc_dbuser"]
password = os.environ.get("dbc_dbpass")

loginstring = quote_plus(user)
if password:
    loginstring += ":" + quote_plus(password)
print(loginstring)
  '
}

# get_sqlalchemy_uri
#
# Generate a database uri using the given dbc configuration
get_sqlalchemy_uri() {
  if [ "${dbc_dbtype}" = pgsql ]; then
    scheme=postgres
  elif [ "${dbc_dbtype}" = mysql ]; then
    scheme="mysql+mysqldb"
  else
    scheme="${dbc_dbtype}"
  fi

  params=""

  if [ "${dbc_dbport}" != "" ]; then
      dbport=":${dbc_dbport}"
  else
      dbport=""
  fi

  echo "${scheme}://$(escape_login)@${dbc_dbserver}${dbport}/${dbc_dbname}${params}"
}

# configure_sql [sqlalchemy url]
#
# This incorporates previously-determined SQL configuration
# information into the linotp.cfg file.

configure_sql() {
  # Escape hash character for use in sed substitution: # -> \#
  escaped_uri="$(echo "$1" | sed  's/#/\#/')"
  cat <<-EOF > $LINOTP_CONFIG_FILE
# This file is generated by the debian configuration system.
#
# LinOTP database configuration
# This URI configures Sqlalchemy to access the LinOTP database.
#
# To change this setting, reconfigure the package using debconf:
#
#   dpkg-reconfigure linotp
DATABASE_URI="${escaped_uri}"
EOF
  # The database password is in this file, so protect accordingly
  chown $LINOTP_USER $LINOTP_CONFIG_FILE
  chmod 600 $LINOTP_CONFIG_FILE
  echo_log "SQL configuration in $LINOTP_CONFIG_FILE created."
}

# init_database
#
# Create and setup required SQL database tables
init_database() {
  echo_log "Initialising database"
  runuser --user $LINOTP_USER -- /usr/bin/linotp init database
}

# configure_and_init_db
#
# Do all the steps needed to configure and initialise
# or migrate the database
#  - write configuration file
#  - initialise or migrate tables
configure_and_init_db() {
  configure_sql "$(get_sqlalchemy_uri)"
  init_database
}