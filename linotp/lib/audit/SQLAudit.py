# -*- coding: utf-8 -*-
#
#    LinOTP - the open source solution for two factor authentication
#    Copyright (C) 2010 - 2019 KeyIdentity GmbH
#
#    This file is part of LinOTP server.
#
#    This program is free software: you can redistribute it and/or
#    modify it under the terms of the GNU Affero General Public
#    License, version 3, as published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the
#               GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#
#    E-mail: linotp@keyidentity.com
#    Contact: www.linotp.org
#    Support: www.keyidentity.com
#
"""
This is the Audit Class, that writes Audits to SQL DB

uses a public/private key for signing the log entries

    # create keypair:
    # openssl genrsa -out private.pem 2048
    # extract the public key:
    # openssl rsa -in private.pem -pubout -out public.pem

"""

import datetime
import logging
from binascii import unhexlify

from sqlalchemy import Column, and_, asc, desc, or_, schema, types
from sqlalchemy.orm import validates

from flask import current_app

from linotp.lib.audit.base import AuditBase
from linotp.lib.crypto.rsa import RSA_Signature
from linotp.model import db, implicit_returning

log = logging.getLogger(__name__)


def now():
    u_now = "%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    return u_now


######################## MODEL ################################################


class AuditTable(db.Model):
    __table_args__ = {
        "implicit_returning": implicit_returning,
    }

    __tablename__ = "audit"
    id = Column(
        types.Integer,
        schema.Sequence("audit_seq_id", optional=True),
        primary_key=True,
    )
    timestamp = Column(types.Unicode(30), default=now, index=True)
    signature = Column(types.Unicode(512), default="")
    action = Column(types.Unicode(30), index=True)
    success = Column(types.Unicode(30), default="0")
    serial = Column(types.Unicode(30), index=True)
    tokentype = Column(types.Unicode(40))
    user = Column(types.Unicode(255), index=True)
    realm = Column(types.Unicode(255), index=True)
    administrator = Column(types.Unicode(255))
    action_detail = Column(types.Unicode(512), default="")
    info = Column(types.Unicode(512), default="")
    linotp_server = Column(types.Unicode(80))
    client = Column(types.Unicode(80))
    log_level = Column(types.Unicode(20), default="INFO", index=True)
    clearance_level = Column(types.Integer, default=0)

    @validates(
        "serial",
        "action",
        "success",
        "tokentype",
        "user",
        "realm",
        "administrator",
        "linotp_server",
        "client",
        "log_level",
    )
    def convert_str(self, _, value):
        """Converts the validated fields to string on insert"""
        return str(value or "")

    @validates("action_detail", "info")
    def validate_truncate(self, key, value):
        max_len = getattr(self.__class__, key).prop.columns[0].type.length
        if value and len(value) > max_len:
            value = value[: max_len]
        return value


###############################################################################
class Audit(AuditBase):
    """
    Audit Implementation to the generic audit interface

    This class provides audit capabilities mapped to an SQLAlchemy
    backend which has a separate database connection.
    """

    name = "SQlAudit"

    engine = None
    """Database backend engine"""

    session = None
    """Database scoped session maker"""

    def __init__(self, config, engine=None):
        """
        Initialise the audit backend

        Here the audit backend is initialised from the given configuration,
        encryption configuration is setup and a database connection opened.

        By supplying an `engine` parameter to the constructor, it is possible
        to use an existing instance as the backend, so that the audit table
        can form a part of the main database. Note, this is not recommended
        for large production systems because this table will be written to
        frequently.

        @param config Dict of configuration values
        @param engine Use the given existing engine
        """

        super(Audit, self).__init__(config)

        ########################## SESSION ##################################

        self._init_db()
        self._init_sessionmaker()
        self._createdb()

        # initialize signing keys
        self.readKeys()

        self.rsa = RSA_Signature(private=self.private.encode("utf-8"))

    def _init_db(self):
        """
        Get SQL Alchemy engine and sessionmaker for the audit interface
        """

        connect_string = current_app.config["AUDIT_DATABASE_URI"]
        pool_recycle = current_app.config["AUDIT_POOL_RECYCLE"]

        # If implicit_returning is explicitly set to True, we
        # get lots of mysql errors
        # AttributeError: 'MySQLCompiler_mysqldb' object has no
        # attribute 'returning_clause'
        # So we do not mention explicit_returning at all
        implicit_returning = self.config.get(
            "linotpSQL.implicit_returning", True
        )

        self.engine = create_engine(
            connect_string,
            pool_recycle=pool_recycle,
            implicit_returning=implicit_returning,
        )

    def _init_sessionmaker(self):
        """
        Set up session maker in `self.session`
        """
        # Set up the session
        sm = orm.sessionmaker(
            bind=self.engine,
            autoflush=True,
            autocommit=True,
            expire_on_commit=True,
        )
        self.session = orm.scoped_session(sm)

    def _createdb(self):
        """
        Create database tables
        """
        # metadata.bind = self.engine
        # metadata.create_all()
        db.create_all()

    def _attr_to_dict(self, audit_line):

        line = {}
        line["number"] = audit_line.id
        line["id"] = audit_line.id
        line["date"] = str(audit_line.timestamp)
        line["timestamp"] = str(audit_line.timestamp)
        line["missing_line"] = ""
        line["serial"] = audit_line.serial
        line["action"] = audit_line.action
        line["action_detail"] = audit_line.action_detail
        line["success"] = audit_line.success
        line["token_type"] = audit_line.tokentype
        line["tokentype"] = audit_line.tokentype
        line["user"] = audit_line.user
        line["realm"] = audit_line.realm
        line["administrator"] = audit_line.administrator
        line["action_detail"] = audit_line.action_detail
        line["info"] = audit_line.info
        line["linotp_server"] = audit_line.linotp_server
        line["client"] = audit_line.client
        line["log_level"] = audit_line.log_level
        line["clearance_level"] = audit_line.clearance_level

        return line

    def _sign(self, audit_line):
        """
        Create a signature of the audit object
        """
        line = self._attr_to_dict(audit_line)
        s_audit = getAsBytes(line)

        signature = self.rsa.sign(s_audit)
        return signature.hex()

    def _verify(self, auditline, signature):
        """
        Verify the signature of the audit line
        """
        res = False
        if not signature:
            log.debug("[_verify] missing signature %r", auditline)
            return res

        s_audit = getAsBytes(auditline)

        return self.rsa.verify(s_audit, unhexlify(signature))

    def log(self, param):
        """
        This method is used to log the data. It splits information of
        multiple tokens (e.g from import) in multiple audit log entries
        """

        try:
            serial = param.get("serial", "") or ""
            if not serial:
                # if no serial, do as before
                self.log_entry(param)
            else:
                # look if we have multiple serials inside
                serials = serial.split(",")
                for serial in serials:
                    p = {}
                    p.update(param)
                    p["serial"] = serial
                    self.log_entry(p)

        except Exception as exx:
            log.error("[log] error writing log message")
            self.session.rollback()
            raise exx

        return

    def log_entry(self, param):
        """
        This method is used to log the data.
        It should hash the data and do a hash chain and sign the data
        """

        at = AuditTable(
            serial=param.get("serial"),
            action=param.get("action").lstrip("/"),
            success="1" if param.get("success") else "0",
            tokentype=param.get("token_type"),
            user=param.get("user"),
            realm=param.get("realm"),
            administrator=param.get("administrator"),
            action_detail=param.get("action_detail"),
            info=param.get("info"),
            linotp_server=param.get("linotp_server"),
            client=param.get("client"),
            log_level=param.get("log_level"),
            clearance_level=param.get("clearance_level"),
        )

        self.session.add(at)
        self.session.flush()
        # At this point "at" contains the primary key id
        at.signature = self._sign(at)
        self.session.merge(at)
        self.session.flush()

    def initialize_log(self, param):
        """
        This method initialized the log state.
        The fact, that the log state was initialized, also needs to be logged.
        Therefor the same params are passed as i the log method.
        """
        pass

    def set(self):
        """
        This function could be used to set certain things like the signing key.
        But maybe it should only be read from linotp.cfg?
        """
        pass

    def _buildCondition(self, param, AND):
        """
        create the sqlalchemy condition from the params
        """
        conditions = []
        boolCheck = and_
        if not AND:
            boolCheck = or_

        for k, v in list(param.items()):
            if "" != v:
                if "serial" == k:
                    conditions.append(AuditTable.serial.like(v))
                elif "user" == k:
                    conditions.append(AuditTable.user.like(v))
                elif "realm" == k:
                    conditions.append(AuditTable.realm.like(v))
                elif "action" == k:
                    conditions.append(AuditTable.action.like(v))
                elif "action_detail" == k:
                    conditions.append(AuditTable.action_detail.like(v))
                elif "date" == k:
                    conditions.append(AuditTable.timestamp.like(v))
                elif "number" == k:
                    conditions.append(AuditTable.id.like(v))
                elif "success" == k:
                    conditions.append(AuditTable.success.like(v))
                elif "tokentype" == k:
                    conditions.append(AuditTable.tokentype.like(v))
                elif "administrator" == k:
                    conditions.append(AuditTable.administrator.like(v))
                elif "info" == k:
                    conditions.append(AuditTable.info.like(v))
                elif "linotp_server" == k:
                    conditions.append(AuditTable.linotp_server.like(v))
                elif "client" == k:
                    conditions.append(AuditTable.client.like(v))

        all_conditions = None
        if conditions:
            all_conditions = boolCheck(*conditions)

        return all_conditions

    def row2dict(self, audit_line):
        """
        convert an SQL audit db to a audit dict

        :param audit_line: audit db row
        :return: audit entry dict
        """

        line = self._attr_to_dict(audit_line)

        # replace None values with an empty string
        for key, value in list(line.items()):
            if value is None:
                line[key] = ""

        # Signature check
        # TODO: use instead the verify_init

        res = self._verify(line, audit_line.signature)
        if res == 1:
            line["sig_check"] = "OK"
        else:
            line["sig_check"] = "FAIL"

        return line

    def searchQuery(self, param, AND=True, display_error=True, rp_dict=None):
        """
        This function is used to search audit events.

        param:
            Search parameters can be passed.

        return:
            a result object which has to be converted with iter() to an
            iterator
        """

        if rp_dict is None:
            rp_dict = {}

        if "or" in param:
            if "true" == param["or"].lower():
                AND = False

        # build the condition / WHERE clause
        condition = self._buildCondition(param, AND)

        order = AuditTable.id
        if rp_dict.get("sortname"):
            sortn = rp_dict.get("sortname").lower()
            if "serial" == sortn:
                order = AuditTable.serial
            elif "number" == sortn:
                order = AuditTable.id
            elif "user" == sortn:
                order = AuditTable.user
            elif "action" == sortn:
                order = AuditTable.action
            elif "action_detail" == sortn:
                order = AuditTable.action_detail
            elif "realm" == sortn:
                order = AuditTable.realm
            elif "date" == sortn:
                order = AuditTable.timestamp
            elif "administrator" == sortn:
                order = AuditTable.administrator
            elif "success" == sortn:
                order = AuditTable.success
            elif "tokentype" == sortn:
                order = AuditTable.tokentype
            elif "info" == sortn:
                order = AuditTable.info
            elif "linotp_server" == sortn:
                order = AuditTable.linotp_server
            elif "client" == sortn:
                order = AuditTable.client
            elif "log_level" == sortn:
                order = AuditTable.log_level
            elif "clearance_level" == sortn:
                order = AuditTable.clearance_level

        # build the ordering
        order_dir = asc(order)

        if rp_dict.get("sortorder"):
            sorto = rp_dict.get("sortorder").lower()
            if "desc" == sorto:
                order_dir = desc(order)

        if condition is None:
            audit_q = self.session.query(AuditTable).order_by(order_dir)
        else:
            audit_q = (
                self.session.query(AuditTable)
                .filter(condition)
                .order_by(order_dir)
            )

        # FIXME? BUT THIS IS SO MUCH SLOWER!
        # FIXME: Here desc() ordering also does not work! :/

        if "rp" in rp_dict or "page" in rp_dict:
            # build the LIMIT and OFFSET
            page = 1
            offset = 0
            limit = 15

            if "rp" in rp_dict:
                limit = int(rp_dict.get("rp"))

            if "page" in rp_dict:
                page = int(rp_dict.get("page"))

            offset = limit * (page - 1)

            start = offset
            stop = offset + limit
            audit_q = audit_q.slice(start, stop)

        # we drop here the ORM due to memory consumption
        # and return a resultproxy for row iteration
        result = self.session.execute(audit_q.statement)
        return result

    def getTotal(self, param, AND=True, display_error=True):
        """
        This method returns the total number of audit entries in
        the audit store
        """
        condition = self._buildCondition(param, AND)
        if type(condition).__name__ == "NoneType":
            c = self.session.query(AuditTable).count()
        else:
            c = self.session.query(AuditTable).filter(condition).count()

        return c


def getAsString(data):
    """
    We need to distinguish, if this is an entry after the adding the
    client entry or before. Otherwise the old signatures will break!
    """

    s = (
        "number=%s, date=%s, action=%s, %s, serial=%s, %s, user=%s, %s,"
        " admin=%s, %s, %s, server=%s, %s, %s"
    ) % (
        str(data.get("id")),
        str(data.get("timestamp")),
        data.get("action"),
        str(data.get("success")),
        data.get("serial"),
        data.get("tokentype"),
        data.get("user"),
        data.get("realm"),
        data.get("administrator"),
        data.get("action_detail"),
        data.get("info"),
        data.get("linotp_server"),
        data.get("log_level"),
        str(data.get("clearance_level")),
    )

    if "client" in data:
        s += ", client=%s" % data.get("client")
    return s


def getAsBytes(data):
    """
    Return the audit record in a bytes format that can be used
    for signing
    """
    return bytes(getAsString(data), "utf-8")


class AuditLinOTPDB(Audit):
    """
    SQL audit backend that uses LinOTP database

    This backend is mainly to allow simple configuration scenario
    where a separate engine is not required
    """

    name = "SQLAudit-LinOTPDB"

    def __init__(self, config):
        """
        Iniailise the audit backend using the LinOTP
        database backend
        """
        super().__init__(config, None)

    def _init_db(self):
        """
        Initialise engine using LinOTP DB
        """
        self.engine = db.engine

    def _init_sessionmaker(self):
        """
        Set up session maker in `self.session`
        """
        self.session = db.session

    def log_entry(self, param):
        super().log_entry(param)
        self.session.commit()


###eof#########################################################################
