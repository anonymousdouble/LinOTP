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
'''The Controller's Base class '''

from inspect import getargspec
from types import FunctionType
import logging
import re

from flask import Blueprint, Response

from linotp.flap import request

# this is a hack for the static code analyser, which
# would otherwise show session.close() as error
import linotp.model.meta

from linotp.lib.context import request_context
from linotp.lib.user import getUserFromParam
from linotp.lib.user import NoResolverFound

log = logging.getLogger(__name__)

Session = linotp.model.meta.Session


class ControllerMetaClass(type):
    """This is used to determine the list of methods of a new
    controller that should be made available as API endpoints.
    Basically every method whose name does not start with an
    underscore has a Flask route to it added in the blueprint
    when a controller class is instantiated.
    """

    def __new__(meta, name, bases, dct):
        """When creating the new class, put a list of all its methods
        whose names do not start with `_` into the `_url_methods` class
        attribute. To support inheritance, we also add the content of
        the `_url_methods` attributes of any base classes.

        Note that we don't do this for the `BaseController` class. This
        is (a) because the `BaseController` does not actually contain
        routable API-endpoint methods, and (b) it contains so many
        utility methods that are not API endpoints that it would be
        a hassle to prefix all of their names with `_`.
        """

        cls = super(ControllerMetaClass, meta).__new__(meta, name, bases, dct)

        if name == 'BaseController':
            cls._url_methods = set()
        else:
            cls._url_methods = {
                m for b in bases for m in getattr(b, '_url_methods', [])
            }
            for key, value in dct.items():
                if key[0] != '_' and isinstance(value, FunctionType):
                    cls._url_methods.add(key)
        return cls


class BaseController(Blueprint):
    """
    BaseController class - will be called with every request
    """
    __metaclass__ = ControllerMetaClass

    def __init__(self, name, install_name='', **kwargs):
        super(BaseController, self).__init__(name, __name__, **kwargs)

        # Add routes for all the routeable endpoints in this "controller",
        # as well as base classes.

        for method_name in self._url_methods:
            # Route the method to a URL of the same name,
            # except for index, which is routed to
            # /<controller-name>/
            if method_name == 'index':
                url = '/'
            else:
                url = '/' + method_name

            method = getattr(self, method_name)

            # We can't set attributes on instancemethod objects but we
            # can set attributes on the underlying function objects.
            if not hasattr(method.__func__, 'methods'):
                method.__func__.methods = ('GET', 'POST')

            # Add another route if the method has an optional second
            # parameter called `id` (and no parameters after that).
            args, _, _, defaults = getargspec(method)
            if ((len(args) == 2 and args[1] == 'id')
                and (defaults is not None and len(defaults) == 1
                     and defaults[0] is None)):
                self.add_url_rule(url, method_name, view_func=method)
                self.add_url_rule(url + '/<id>', method_name, view_func=method)
            else:
                # Otherwise, add any parameters of the method to the end
                # of the route, in order.
                for arg in args:
                    if arg != 'self':
                        url += '/<' + arg + '>'
                self.add_url_rule(url, method_name, view_func=method)

    def before_handler(self):

        params = self.request_params

        if hasattr(self, '__before__'):

            response = self.__before__(**params)

            # in case of exceptions / errors the __before__ handling submits an sendError
            # flask.Response which has the special attribute _exception
            # which is set in the lib/reply.py

            if isinstance(response, Response) and hasattr(response, '_exception'):
                return response

def methods(mm=['GET']):
    """
    Decorator to specify the allowable HTTP methods for a
    controller/blueprint method. It turns out that `Flask.add_url_rule`
    looks at a function object's `methods` property when figuring out
    what HTTP methods should be allowed on a view, so that's where we're
    putting the methods list.
    """

    def inner(func):
        func.methods = mm[:]
        return func
    return inner

# eof ########################################################################

