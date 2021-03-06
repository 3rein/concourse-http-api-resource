#!/usr/bin/env python3

import json
import logging as log
import os
import sys
import tempfile
from ast import literal_eval

import requests


class HTTPResource:
    """HTTP resource implementation."""

    def cmd(self, arg, data):
        """Make the requests."""

        method = data.get('method', 'GET')
        uri = data['uri']
        headers = data.get('headers', {})
        json_data = data.get('json', None)
        ssl_verify = data.get('ssl_verify', True)
        ok_responses = data.get('ok_responses', [200, 201, 202, 204])
        form_data = data.get('form_data')
        verify = False

        if isinstance(ssl_verify, bool):
            verify = ssl_verify
        elif isinstance(ssl_verify, str):
            verify = str(tempfile.NamedTemporaryFile(delete=False, prefix='ssl-').write(str.encode(ssl_verify)))

        request_data = None
        if form_data:
            request_data = {k: json.dumps(v, ensure_ascii=False) for k, v in form_data.items()}

        response = requests.request(method, uri, json=json_data,
                                    data=request_data, headers=headers, verify=verify)

        log.info('http response code: %s', response.status_code)
        log.info('http response text: %s', response.text)

        if response.status_code not in ok_responses:
            raise Exception('Unexpected response {}'.format(response.status_code))

        return response.status_code, response.text

    def run(self, command_name: str, json_data: str, command_argument: str):
        """Parse input/arguments, perform requested command return output."""

        with tempfile.NamedTemporaryFile(delete=False, prefix=command_name + '-') as f:
            f.write(bytes(json_data, 'utf-8'))

        data = json.loads(json_data)

        # allow debug logging to console for tests
        if os.environ.get('RESOURCE_DEBUG', False) or data.get('source', {}).get('debug', False):
            log.basicConfig(level=log.DEBUG)
        else:
            logfile = tempfile.NamedTemporaryFile(delete=False, prefix='log')
            log.basicConfig(level=log.DEBUG, filename=logfile.name)
            stderr = log.StreamHandler()
            stderr.setLevel(log.INFO)
            log.getLogger().addHandler(stderr)

        log.debug('command: %s', command_name)
        log.debug('input: %s', data)
        log.debug('args: %s', command_argument)
        log.debug('environment: %s', os.environ)

        # initialize values with Concourse environment variables
        values = {k: v for k, v in os.environ.items() if k.startswith('BUILD_') or k == 'ATC_EXTERNAL_URL'}

        # combine source and params
        params = data.get('source', {})
        params.update(data.get('params', {}))

        # allow also to interpolate params
        values.update(params)

        # apply templating of environment variables onto parameters
        rendered_params = self._interpolate(params, self._read_file_as_text(values))

        status_code, text = self.cmd(command_argument, rendered_params)

        # return empty version object
        response = {"version": {}}

        if os.environ.get('TEST', False):
            response.update(json.loads(text))

        return json.dumps(response)

    def _interpolate(self, data, values):
        """Recursively apply values using format on all string key and values in data."""

        if isinstance(data, str):
            formatted_data = data.format(**values)
            try:
                evaluated_data = literal_eval(formatted_data)
                if isinstance(evaluated_data, list) or isinstance(evaluated_data, dict):
                    return evaluated_data
            except Exception:
                pass
            return formatted_data
        elif isinstance(data, list):
            return [self._interpolate(x, values) for x in data]
        elif isinstance(data, dict):
            return {
                self._interpolate(k, values): self._interpolate(v, values)
                for k, v in data.items()
            }
        else:
            return data

    def _read_file_as_text(self, values):
        """Recursively replace file references with their contents."""

        if isinstance(values, str):
            if values.startswith('file:'):
                with open('/tmp/build/put/' + values.partition('file:')[2].strip()) as file:
                    values = file.read().strip()
                try:
                    return json.loads(values)
                except ValueError:
                    pass
            return values
        elif isinstance(values, list):
            return [self._read_file_as_text(x) for x in values]
        elif isinstance(values, dict):
            return {
                self._read_file_as_text(k): self._read_file_as_text(v)
                for k, v in values.items()
            }
        else:
            return values


print(HTTPResource().run(os.path.basename(__file__), sys.stdin.read(), sys.argv[1:]))
