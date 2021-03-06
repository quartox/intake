#-----------------------------------------------------------------------------
# Copyright (c) 2012 - 2018, Anaconda, Inc. and Intake contributors
# All rights reserved.
#
# The full license is in the LICENSE file, distributed with this software.
#-----------------------------------------------------------------------------

import msgpack
import requests
from requests.compat import urljoin
import six

from ..source import registry as plugin_registry
from .entry import CatalogEntry
from .utils import expand_defaults, coerce
from ..compat import unpack_kwargs


class RemoteCatalogEntry(CatalogEntry):
    """An entry referring to a remote data definition"""
    def __init__(self, url, auth, name=None, user_parameters=None,
                 container=None, description='', metadata=None,
                 http_args=None, page_size=None, direct_access=False,
                 getenv=True, getshell=True):
        """

        Parameters
        ----------
        url: str
            HTTP address of the Intake server this entry comes from
        auth: Auth instance
            If there are additional headers to add to calls, this instance will
            provide them
        kwargs: additional keys describing the entry, name, description,
            container,
        """
        self.url = url
        self.auth = auth
        self.container = container
        self.name = name
        self.description = description
        self._metadata = metadata or {}
        self._page_size = page_size
        self._user_parameters = user_parameters or []
        self._direct_access = direct_access
        self.http_args = (http_args or {}).copy()
        if 'headers' not in self.http_args:
            self.http_args['headers'] = {}
        super(RemoteCatalogEntry, self).__init__(getenv=getenv,
                                                 getshell=getshell)

    @property
    def kwargs(self):
        return dict(name=self.name,
                    container=self.container, description=self.description,
                    direct_access=self._direct_access,
                    user_parameters=self._user_parameters
                    )

    def describe(self):
        return self.kwargs

    def describe_open(self, **kwargs):
        return {
            'container': self.container,
            'plugin': None,
            'description': self._description,
            'direct_access': self._direct_access,
            'metadata': self._metadata,
            'args': (self.url, )
        }

    def get(self, **user_parameters):
        for par in self._user_parameters:
            if par['name'] not in user_parameters:
                default = par['default']
                if isinstance(default, six.string_types):
                    default = coerce(par['type'], expand_defaults(
                        par['default'], True, self.getenv, self.getshell))
                user_parameters[par['name']] = default

        http_args = self.http_args.copy()
        http_args['headers'] = self.http_args['headers'].copy()
        http_args['headers'].update(self.auth.get_headers())
        return open_remote(
            self.url, self.name, container=self.container,
            user_parameters=user_parameters, description=self.description,
            http_args=http_args,
            page_size=self._page_size,
            auth=self.auth,
            getenv=self.getenv,
            getshell=self.getshell)


def open_remote(url, entry, container, user_parameters, description, http_args,
                page_size=None, auth=None, getenv=None, getshell=None):
    """Create either local direct data source or remote streamed source"""
    from intake.container import container_map
    if url.startswith('intake://'):
        url = url[len('intake://'):]
    payload = dict(action='open',
                   name=entry,
                   parameters=user_parameters,
                   available_plugins=list(plugin_registry.keys()))
    req = requests.post(urljoin(url, '/v1/source'),
                        data=msgpack.packb(payload, use_bin_type=True),
                        **http_args)
    if req.ok:
        response = msgpack.unpackb(req.content, **unpack_kwargs)

        if 'plugin' in response:
            # Direct access
            source = plugin_registry[response['plugin']](**response['args'])
            source.description = description
        else:
            # Proxied access
            response.pop('container')
            response.update({'name': entry, 'parameters': user_parameters})
            if container == 'catalog':
                response.update({'auth': auth,
                                 'getenv': getenv,
                                 'getshell': getshell,
                                 'page_size': page_size
                                 # TODO ttl?
                                 # TODO storage_options?
                                 })
            source = container_map[container](url, http_args, **response)
        return source

    else:
        raise Exception('Server error: %d, %s' % (req.status_code, req.reason))
