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
helpdesk controller - interfaces to administrate LinOTP as helpdesk
"""
import os
import logging

from pylons import request
from pylons import response
from pylons import config
from pylons import tmpl_context as c

from linotp.lib.base import BaseController

from linotp.lib.reply import sendResult
from linotp.lib.reply import sendError

from linotp.lib.user import User

from linotp.lib.user import getUserFromParam
from linotp.lib.user import getUserFromRequest

from linotp.lib.policy import checkPolicyPre
from linotp.lib.policy import checkPolicyPost
from linotp.lib.policy import PolicyException

from linotp.lib.policy import getAdminPolicies
from linotp.tokens import tokenclass_registry

from linotp.lib.tokeniterator import TokenIterator
from linotp.lib.token import TokenHandler

from linotp.lib.util import get_client

from linotp.lib.error import ParameterError
from linotp.lib.error import TokenAdminError

from linotp.lib.context import request_context
from linotp.lib.realm import getRealms

from linotp.lib.user import getUserList

from linotp.lib.util import unicode_compare, SESSION_KEY_LENGTH

from linotp.provider import notify_user

from linotp.lib.audit.base import logTokenNum

from linotp.lib.realm import get_realms_from_params

import linotp.model
Session = linotp.model.Session

audit = config.get('audit')


log = logging.getLogger(__name__)


class HelpdeskController(BaseController):

    '''
    The linotp.controllers are the implementation of the web-API to talk to
    the LinOTP server.
    The HelpdeskController is used for administrative tasks like adding tokens
    to LinOTP, assigning tokens or revoking tokens.
    The functions of the AdminController are invoked like this

        https://server/helpdesk/<functionname>

    The functions are described below in more detail.
    '''

    def __before__(self, action, **params):
        '''
        '''

        try:

            c.audit = request_context['audit']
            c.audit['success'] = False
            c.audit['client'] = get_client(request)

            # Session handling
            #check_session(request)

            request_context['Audit'] = audit
            return request

        except Exception as exx:
            log.exception("[__before__::%r] exception %r", action, exx)
            Session.rollback()
            Session.close()
            return sendError(response, exx, context='before')

    def __after__(self, action):
        '''
        '''

        try:
            c.audit['administrator'] = getUserFromRequest(request).get("login")
            c.audit['serial'] = self.request_params.get('serial')

            audit.log(c.audit)
            Session.commit()

            return request

        except Exception as e:
            log.exception("[__after__] unable to create a session cookie: %r" % e)
            Session.rollback()
            return sendError(response, e, context='after')

        finally:
            Session.close()


    def getsession(self):
        '''
        This generates a session key and sets it as a cookie
        set_cookie is defined in python-webob::

            def set_cookie(self, key, value='', max_age=None,
                   path='/', domain=None, secure=None, httponly=False,
                   version=None, comment=None, expires=None, overwrite=False):
        '''
        import binascii
        try:
            web_host = request.environ.get('HTTP_HOST')
            # HTTP_HOST also contains the port number. We need to stript this!
            web_host = web_host.split(':')[0]
            log.debug("[getsession] environment: %s" % request.environ)
            log.debug("[getsession] found this web_host: %s" % web_host)
            random_key = os.urandom(SESSION_KEY_LENGTH)
            cookie = binascii.hexlify(random_key)
            log.debug("[getsession] adding session cookie %s to response." % cookie)
            # we send all three to cope with IE8
            response.set_cookie('helpdesk_session', value=cookie, domain=web_host)
            # this produces an error with the gtk client
            # response.set_cookie('admin_session', value=cookie,  domain=".%" % web_host )
            response.set_cookie('helpdesk_session', value=cookie, domain="")
            return sendResult(response, True)

        except Exception as e:
            log.exception("[getsession] unable to create a session cookie: %r" % e)
            Session.rollback()
            return sendError(response, e)

        finally:
            Session.close()

    def dropsession(self):
        response.set_cookie('helpdesk_session', None, expires=1)
        return sendResult(response, True)
