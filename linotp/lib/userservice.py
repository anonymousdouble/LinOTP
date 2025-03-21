# -*- coding: utf-8 -*-
#
#    LinOTP - the open source solution for two factor authentication
#    Copyright (C) 2010-2019 KeyIdentity GmbH
#    Copyright (C) 2019-     netgo software GmbH
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
#    E-mail: info@linotp.de
#    Contact: www.linotp.org
#    Support: www.linotp.de
#
""" logic for the userservice processing """

import base64
import binascii
import copy
import datetime
import hashlib
import hmac
import json
import logging
import os

# for the temporary rendering context, we use 'c'
from linotp.flap import render_mako as render
from linotp.flap import tmpl_context as c
from linotp.lib.challenges import Challenges
from linotp.lib.context import request_context
from linotp.lib.policy.action import (
    get_selfservice_action_value,
    get_selfservice_actions,
)
from linotp.lib.realm import getDefaultRealm, getRealms
from linotp.lib.selfservice import get_imprint
from linotp.lib.token import get_tokens
from linotp.lib.type_utils import DEFAULT_TIMEFORMAT as TIMEFORMAT
from linotp.lib.type_utils import parse_duration
from linotp.lib.user import User, get_userinfo, getRealmBox
from linotp.lib.util import get_copyright_info, get_request_param, get_version
from linotp.tokens import tokenclass_registry

log = logging.getLogger(__name__)

# const for encryption and iv
SECRET_LEN = 32

Cookie_Secret = binascii.hexlify(os.urandom(SECRET_LEN))
Cookie_Cache = {}


def getTokenForUser(user, active=None, exclude_rollout=True):
    """
    should be moved to token.py
    """
    tokenArray = []

    log.debug("[getTokenForUser] iterating tokens for user...")
    log.debug(
        "[getTokenForUser] ...user %s in realm %s.", user.login, user.realm
    )

    tokens = get_tokens(user=user, serial=None, active=active)

    for token in tokens:
        tok = token.token.get_vars()
        if tok.get("LinOtp.TokenInfo", None):
            token_info = json.loads(tok.get("LinOtp.TokenInfo"))

            # skip the rollout tokens from the selfservice token list

            path = token_info.get("scope", {}).get("path", [])
            if (
                set(path) & set(["userservice", "validate"])
                and exclude_rollout
            ):
                continue

            tok["LinOtp.TokenInfo"] = token_info

        tok["Enrollment"] = token.get_enrollment_status()

        tokenArray.append(tok)

    log.debug("[getTokenForUser] found tokenarray: %r", tokenArray)
    return tokenArray


def _get_realms_():
    realms = {}
    if getRealmBox():
        realms = getRealms()
    else:
        def_realm = getDefaultRealm()
        if getDefaultRealm():
            realms = getRealms(def_realm)
    return realms


def create_auth_cookie(user, client, state="authenticated", state_data=None):
    """
    create and auth_cookie value from the authenticated user and client

    :param user: the authenticated user
    :param client: the requesting client
    :param state: the state info for the authentication
    :return: the hmac256digest of the user data
             the expiration time as datetime
             the expiration time as string
    """

    secret = get_cookie_secret()
    key = binascii.unhexlify(secret)

    # ---------------------------------------------------------------------- --

    # handle expiration calculation

    expiry = get_cookie_expiry()

    if expiry is False:
        # default should be at max 1 hour
        delta = datetime.timedelta(seconds=1 * 60 * 60)
    else:
        delta = parse_duration(expiry)

    now = datetime.datetime.utcnow()
    expires = now + delta
    expiration = expires.strftime(TIMEFORMAT)

    # ---------------------------------------------------------------------- --

    # build the cache data
    if state_data is not None:
        state_data = copy.deepcopy(state_data)

    # we have to serialize the user object
    # - we do this currently in a very limited way where the resolver
    # specification is missing!

    user_dict = {"login": user.login, "realm": user.realm}

    data = [user_dict, client, expiration, state, state_data]
    hash_data = ("%r" % data).encode("utf-8")

    digest = hmac.new(key, hash_data, digestmod=hashlib.sha256).digest()
    auth_cookie = base64.urlsafe_b64encode(digest).decode().strip("=")

    Cookie_Cache[auth_cookie] = data

    return auth_cookie, expires, expiration


def get_cookie_authinfo(cookie):
    """
    return the authentication data from the cookie, which is the user
    and the auth state and the optional state_data

    :param cookie: the session cookie, which is an hmac256 hash
    :return: triple of user, state and state_data
    """

    data = Cookie_Cache.get(cookie)

    if not data:
        return None, None, None, None

    [u_dict, client, expiration, state, state_data] = data

    # handle session expiration

    now = datetime.datetime.utcnow()
    expires = datetime.datetime.strptime(expiration, TIMEFORMAT)
    if now > expires:
        log.info("session is expired")
        return None, None, None, None

    user = User(login=u_dict.get("login", ""), realm=u_dict.get("realm", ""))
    return user, client, state, state_data


def remove_auth_cookie(cookie):
    """
    verify that value of the auth_cookie contains the correct user and client

    :param user: the authenticated user object
    :param cookie: the auth_cookie
    :param client: the requesting client

    :return: boolean
    """

    if cookie in Cookie_Cache:
        del Cookie_Cache[cookie]


def check_auth_cookie(cookie, user, client):
    """
    verify that value of the auth_cookie contains the correct user and client

    :param user: the authenticated user object
    :param cookie: the auth_cookie
    :param client: the requesting client

    :return: boolean
    """

    data = Cookie_Cache.get(cookie)

    if not data:
        return False

    [cookie_user_dict, cookie_client, expiration, _state, _state_data] = data

    cookie_user = User(
        login=cookie_user_dict.get("login"),
        realm=cookie_user_dict.get("realm"),
    )
    # handle session expiration

    now = datetime.datetime.utcnow()
    expires = datetime.datetime.strptime(expiration, TIMEFORMAT)

    if now > expires:
        log.info("session is expired")
        return False

    if client is None and not cookie_client:
        cookie_client = None

    return user == cookie_user and cookie_client == client


def get_cookie_secret():
    """
    get the cookie encryption secret from the config
    - if the selfservice is droped from running localy, this
      configuration option might not exist anymore

    :return: return the cookie encryption secret
    """
    return Cookie_Secret


def get_cookie_expiry():
    """
    get the cookie encryption expiry from the config
    - if the selfservice is dropped from running locally, this
      configuration option might not exist anymore

    :return: return the cookie encryption expiry
    """
    config = request_context["Config"]

    return config.get("selfservice.auth_expiry", False)


def check_session(request, user, client):
    """
    check if the user session is ok:
    - check if the sessionvalue is the same as the cookie
    - check if the user has been authenticated before by decrypt the cookie val

    :param request: the request context
    :param user:the authenticated user
    :param client: the cookie is bouind to the client

    :return: boolean
    """

    # try to get (local) selfservice
    # if none is present fall back to possible
    # userauthcookie (cookie for remote self service)

    session = get_request_param(request, "session", "no_session")

    for cookie_ref in ["user_selfservice", "userauthcookie"]:
        cookie = request.cookies.get(cookie_ref, "no_auth_cookie")

        if session == cookie:
            return check_auth_cookie(cookie, user, client)

    return False


def get_pre_context(client):
    """
    get the rendering context before the login is shown, so the rendering
    of the login page could be controlled if realm_box or mfa_login is
    defined

    :param client: the rendering is client dependend, so we need the info
    :return: context dict, with all rendering attributes
    """

    # check for mfa_login, autoassign and autoenroll in policy definition
    mfa_login_action = get_selfservice_action_value(
        action="mfa_login", default=False
    )

    mfa_3_fields_action = get_selfservice_action_value(
        action="mfa_3_fields", default=False
    )

    autoassignment_action = get_selfservice_action_value(
        action="autoassignment", default=False
    )

    autoenrollment_action = get_selfservice_action_value(
        action="autoenrollment", default=False
    )

    footer_text_action = get_selfservice_action_value(
        action="footer_text", default=None
    )

    imprint_url_action = get_selfservice_action_value(
        action="imprint_url", default=None
    )

    privacy_notice_url_action = get_selfservice_action_value(
        action="privacy_notice_url", default=None
    )

    return {
        "version": get_version(),
        "copyright": get_copyright_info(),
        "realms": _get_realms_(),
        "settings": {
            "default_realm": getDefaultRealm(),
            "realm_box": getRealmBox(),
            "mfa_login": mfa_login_action,
            "mfa_3_fields": mfa_3_fields_action,
            "autoassign": autoassignment_action,
            "autoenroll": autoenrollment_action,
            "footer_text": footer_text_action,
            "imprint_url": imprint_url_action,
            "privacy_notice_url": privacy_notice_url_action,
        },
    }


def get_context(config, user, client):
    """
    get the user dependend rendering context

    :param user: the selfservice auth user
    :param realm: the selfservice realm
    :param client: the selfservice client info - required for pre_context
    :return: context dict, with all rendering attributes

    """
    context = get_pre_context(client)

    context["user"] = get_userinfo(user)
    context["imprint"] = get_imprint(user.realm)
    context["tokenArray"] = getTokenForUser(user)

    context["actions"] = list()
    for action_name, action_value in get_selfservice_actions(user).items():
        if action_value is True:
            context["actions"].append(action_name)
        else:
            context["settings"][action_name] = action_value

    return context


##############################################################################


def add_dynamic_selfservice_enrollment(config, actions):
    """
    add_dynamic_actions - load the html of the dynamic tokens
        according to the policy definition

    :param actions: the allowd policy actions for the current scope
    :type  actions: array of actions names

    :return: hash of {tokentype : html for tab}
    """

    dynanmic_actions = {}

    for tclass_object in set(tokenclass_registry.values()):
        tok = tclass_object.getClassType()
        if hasattr(tclass_object, "getClassInfo"):
            try:
                selfservice = tclass_object.getClassInfo(
                    "selfservice", ret=None
                )
                # # check if we have a policy in the token definition for the enroll
                if (
                    "enroll" in selfservice
                    and "enroll" + tok.upper() in actions
                ):
                    service = selfservice.get("enroll")
                    tab = service.get("title")
                    c.scope = tab.get("scope")
                    t_file = tab.get("html")
                    t_html = render(t_file).decode()
                    """ remove empty lines """
                    t_html = "\n".join(
                        [
                            line
                            for line in t_html.split("\n")
                            if line.strip() != ""
                        ]
                    )
                    e_name = "%s.%s.%s" % (tok, "selfservice", "enroll")
                    dynanmic_actions[e_name] = t_html

                # # check if there are other selfserive policy actions
                policy = tclass_object.getClassInfo("policy", ret=None)
                if "selfservice" in policy:
                    selfserv_policies = list(policy.get("selfservice").keys())
                    for action in actions:
                        if action in selfserv_policies:
                            # # now lookup, if there is an additional section
                            # # in the selfservice to render
                            service = selfservice.get(action)
                            tab = service.get("title")
                            c.scope = tab.get("scope")
                            t_file = tab.get("html")
                            t_html = render(t_file).decode()
                            """ remove empty lines """
                            t_html = "\n".join(
                                [
                                    line
                                    for line in t_html.split("\n")
                                    if line.strip() != ""
                                ]
                            )
                            e_name = "%s.%s.%s" % (tok, "selfservice", action)
                            dynanmic_actions[e_name] = t_html

            except Exception as exx:
                log.info(
                    "[_add_dynamic_actions] no policy for tokentype "
                    "%r found (%r)",
                    tok,
                    exx,
                )

    return dynanmic_actions


def add_dynamic_selfservice_policies(config, actions):
    """
    add_dynamic_actions - load the html of the dynamic tokens
        according to the policy definition

    :param actions: the allowd policy actions for the current scope
    :type  actions: array of actions names

    :return: hash of {tokentype : html for tab}
    """

    dynamic_policies = []

    defined_policies = []

    for tok in tokenclass_registry:
        tclt = tokenclass_registry.get(tok)
        if hasattr(tclt, "getClassInfo"):
            # # check if we have a policy in the token definition
            try:
                policy = tclt.getClassInfo("policy", ret=None)
                if policy is not None and "selfservice" in policy:
                    scope_policies = list(policy.get("selfservice").keys())
                    """ initialize the policies """
                    if len(defined_policies) == 0:
                        for pol in actions:
                            if "=" in pol:
                                (name, val) = pol.split("=")
                                defined_policies.append(name)

                    for local_policy in scope_policies:
                        if local_policy not in defined_policies:
                            dynamic_policies.append(local_policy)
            except Exception as exx:
                log.info(
                    "[_add_dynamic_actions] no policy for tokentype "
                    "%r found (%r)",
                    tok,
                    exx,
                )

    return dynamic_policies


def add_local_policies():
    return


def get_transaction_detail(transactionid):
    """Provide the information about a transaction.

    :param transactionid: the transaction id
    :return: dict with detail about challenge status
    """

    _exp, challenges = Challenges.get_challenges(transid=transactionid)

    if not challenges:
        return {}

    challenge = challenges[0]

    challenge_session = challenge.getSession()
    if challenge_session:
        challenge_session = json.loads(challenge_session)
    else:
        challenge_session = {}

    details = {
        "received_count": challenge.received_count,
        "received_tan": challenge.received_tan,
        "valid_tan": challenge.valid_tan,
        "message": challenge.getChallenge(),
        "status": challenge.getStatus(),
        "accept": challenge_session.get("accept", False),
        "reject": challenge_session.get("reject", False),
    }

    return details
