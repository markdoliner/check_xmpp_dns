#!/usr/bin/env python

# Licensed as follows (this is the 2-clause BSD license, aka
# "Simplified BSD License" or "FreeBSD License"):
#
# Copyright (c) 2011-2014,2019, Mark Doliner
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# - Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

# TODO: Maybe print a friendly warning if a DNS server returns a CNAME record
#       when we query for DNS SRV?  It's possible this is legit, and we should
#       recursively query the CNAME record for DNS SRV. But surely not all
#       XMPP clients will do that.
# TODO: Add mild info/warning if client and server records point to different
#       hosts?  Or resolve to different hosts?  (aegee.org)
# TODO: Better info message if port is 443?  Talk about how clients might not
#       realize they need to use ssl?  (buddycloud.com)
# TODO: Better info message if port is 5223?  Talk about how clients might not
#       realize they need to use ssl?  (biscotti.com)
# TODO: Make sure record.target ends with a period?
# TODO: Add JavaScript to strip leading and trailing whitespace in the
#       hostname before submitting the form, so that the hostname is pretty in
#       the URL.

# import gevent.monkey; gevent.monkey.patch_all()

import cgi
import collections
import enum
import logging
import urllib.parse

# import cgitb; cgitb.enable()
import dns.exception
import dns.resolver
import jinja2


@enum.unique
class NoteType(enum.Enum):
    NON_STANDARD_PORT = enum.auto()
    CLIENT_SERVER_SHARED_PORT = enum.auto()


RecordTuple = collections.namedtuple('RecordTuple', [
    'port',
    'priority',
    'target',
    'weight',
    'note_types_and_footnote_numbers',  # a 2-item tuple
])


def _sort_records(records):
    return sorted(
        records,
        key=lambda record: '%10d %10d %50s %d' % (
            record.priority, 1000000000 - record.weight, record.target, record.port))


def _get_records(records, standard_port, conflicting_records):
    note_types_for_these_records = []

    # Create the list of result rows
    rows = []
    for record in records:
        note_types_for_this_record = set()
        if '%s:%s' % (record.target, record.port) in conflicting_records:
            note_types_for_this_record.add(NoteType.CLIENT_SERVER_SHARED_PORT)
        if record.port != standard_port:
            note_types_for_this_record.add(NoteType.NON_STANDARD_PORT)

        note_types_for_these_records.extend(note_types_for_this_record)
        note_types_and_footnote_numbers = [
            (note_type, note_types_for_these_records.index(note_type) + 1)
            for note_type in note_types_for_this_record
        ]

        rows.append(RecordTuple(
            port=record.port,
            priority=record.priority,
            # Strip trailing period when displaying
            target=str(record.target).rstrip('.'),
            weight=record.weight,
            note_types_and_footnote_numbers=note_types_and_footnote_numbers))

    return (rows, note_types_for_these_records)


def _get_authoritative_name_servers_for_domain(domain):
    """Return a list of strings containing IP addresses of the name servers
    that are considered to be authoritative for the given domain.

    This iteratively queries the name server responsible for each piece of the
    FQDN directly, so as to avoid any caching of results.
    """

    # Create a DNS resolver to use for these requests
    dns_resolver = dns.resolver.Resolver()

    # Set a 2.5 second timeout on the resolver
    dns_resolver.lifetime = 2.5

    # Iterate through the pieces of the hostname from broad to narrow. For
    # each piece, ask which name servers are authoritative for the next
    # narrower piece. Note that we don't bother doing this for the broadest
    # piece of the hostname (e.g. 'com' or 'net') because the list of root
    # servers should rarely change and changes shouldn't affect the outcome
    # of these queries.
    pieces = domain.split('.')
    for i in range(len(pieces)-1, 0, -1):
        broader_domain = '.'.join(pieces[i-1:])
        try:
            answer = dns_resolver.query(broader_domain, dns.rdatatype.NS)
        except dns.exception.SyntaxError:
            # TODO: Show "invalid hostname" for this?
            return None
        except dns.resolver.NXDOMAIN:
            # TODO: Show an error message about this. "Unable to determine
            # authoritative name servers for domain X. These results might be
            # stale, up to the lifetime of the TTL."
            return None
        except dns.resolver.NoAnswer:
            # TODO: Show an error message about this. "Unable to determine
            # authoritative name servers for domain X. These results might be
            # stale, up to the lifetime of the TTL."
            return None
        except dns.resolver.NoNameservers:
            # TODO: Show an error message about this. "Unable to determine
            # authoritative name servers for domain X. These results might be
            # stale, up to the lifetime of the TTL."
            return None
        except dns.resolver.Timeout:
            # TODO: Show an error message about this. "Unable to determine
            # authoritative name servers for domain X. These results might be
            # stale, up to the lifetime of the TTL."
            return None

        new_nameservers = []
        for record in answer:
            if record.rdtype == dns.rdatatype.NS:
                # Got the hostname of a nameserver. Resolve it to an IP.
                # TODO: Don't do this if the nameserver we just queried gave us
                # an additional record that includes the IP.
                try:
                    answer2 = dns_resolver.query(record.to_text())
                except dns.exception.SyntaxError:
                    # TODO: Show "invalid hostname" for this?
                    return None
                except dns.resolver.NXDOMAIN:
                    # TODO: Show an error message about this. "Unable to determine
                    # authoritative name servers for domain X. These results might be
                    # stale, up to the lifetime of the TTL."
                    return None
                except dns.resolver.NoAnswer:
                    # TODO: Show an error message about this. "Unable to determine
                    # authoritative name servers for domain X. These results might be
                    # stale, up to the lifetime of the TTL."
                    return None
                except dns.resolver.NoNameservers:
                    # TODO: Show an error message about this. "Unable to determine
                    # authoritative name servers for domain X. These results might be
                    # stale, up to the lifetime of the TTL."
                    return None
                except dns.resolver.Timeout:
                    # TODO: Show an error message about this. "Unable to determine
                    # authoritative name servers for domain X. These results might be
                    # stale, up to the lifetime of the TTL."
                    return None
                for record2 in answer2:
                    if record2.rdtype in (dns.rdatatype.A, dns.rdatatype.AAAA):
                        # Add the IP to the list of IPs.
                        new_nameservers.append(record2.address)
                    else:
                        # Unexpected record type
                        # TODO: Log something?
                        pass
            else:
                # Unexpected record type
                # TODO: Log something?
                pass

        dns_resolver.nameservers = new_nameservers

    return dns_resolver.nameservers


class RequestHandler:
    def __init__(self, env, start_response):
        self.env = env
        self.start_response = start_response

        # TODO: Using a persistent object for this would perform better.
        # Might need to use gevent.local somehow.
        self.jinja2_env = jinja2.Environment(
            autoescape=True,
            loader=jinja2.FileSystemLoader('templates'),
            undefined=jinja2.StrictUndefined)
        self.jinja2_env.globals = dict(NoteType=NoteType)

    def handle(self):
        form = cgi.FieldStorage(environ=self.env)

        hostname = form['h'].value.strip() if 'h' in form else None
        if hostname:
            response_body = self._look_up_records(hostname)
        else:
            response_body = self.jinja2_env.get_template('index_base.html.jinja').render(
                hostname='')

        self.start_response('200 OK', [('Content-Type', 'text/html')])
        return [response_body.encode('utf-8')]

    def _look_up_records(self, hostname):
        """Looks up the DNS records for the given hostname and returns
        a namedtuple.
        """
        # Record domain name
        open('requestledger.txt', 'a').write('%s\n' % urllib.parse.quote(hostname))

        # Sanity check hostname
        if hostname.find('..') != -1:
            return self.jinja2_env.get_template('index_with_lookup_error.html.jinja').render(
                hostname=hostname,
                error_message='Invalid hostname')

        # Create a DNS resolver to use for this request
        dns_resolver = dns.resolver.Resolver()

        # Set a 2.5 second timeout on the resolver
        dns_resolver.lifetime = 2.5

        # Look up the list of authoritative name servers for this domain and query
        # them directly when looking up XMPP SRV records. We do this to avoid any
        # potential caching from intermediate name servers.
        new_nameservers = _get_authoritative_name_servers_for_domain(hostname)
        if new_nameservers:
            dns_resolver.nameservers = new_nameservers
        else:
            # Couldn't determine authoritative name servers for domain.
            # TODO: Log something? Show message to user?
            pass

        # Lookup records
        try:
            client_records = dns_resolver.query(
                '_xmpp-client._tcp.%s' % hostname, rdtype=dns.rdatatype.SRV)
        except dns.exception.SyntaxError:
            # TODO: Show "invalid hostname" for this
            client_records = []
        except dns.resolver.NXDOMAIN:
            client_records = []
        except dns.resolver.NoAnswer:
            # TODO: Show a specific message for this
            client_records = []
        except dns.resolver.NoNameservers:
            # TODO: Show a specific message for this
            client_records = []
        except dns.resolver.Timeout:
            # TODO: Show a specific message for this
            client_records = []
        client_records_by_endpoint = set(
            '%s:%s' % (record.target, record.port)
            for record in client_records)

        try:
            server_records = dns_resolver.query(
                '_xmpp-server._tcp.%s' % hostname, rdtype=dns.rdatatype.SRV)
        except dns.exception.SyntaxError:
            # TODO: Show "invalid hostname" for this
            server_records = []
        except dns.resolver.NXDOMAIN:
            server_records = []
        except dns.resolver.NoAnswer:
            # TODO: Show a specific message for this
            server_records = []
        except dns.resolver.NoNameservers:
            # TODO: Show a specific message for this
            server_records = []
        except dns.resolver.Timeout:
            # TODO: Show a specific message for this
            server_records = []
        server_records_by_endpoint = set(
            '%s:%s' % (record.target, record.port)
            for record in server_records)

        if client_records:
            client_records = _sort_records(client_records)
            (client_records, client_record_note_types) = _get_records(
                client_records, 5222, server_records_by_endpoint)
        else:
            client_record_note_types = []

        if server_records:
            server_records = _sort_records(server_records)
            (server_records, server_record_note_types) = _get_records(
                server_records, 5269, client_records_by_endpoint)
        else:
            server_record_note_types = []

        return self.jinja2_env.get_template('index_with_successful_lookup.html.jinja').render(
            hostname=hostname,
            client_records=client_records,
            client_record_note_types=client_record_note_types,
            server_records=server_records,
            server_record_note_types=server_record_note_types)


def application(env, start_response):
    """WSGI application entry point."""

    try:
        return RequestHandler(env, start_response).handle()
    except Exception:
        logging.exception('Unknown error handling request. env=%s', env)
        raise


if __name__ == '__main__':
    logging.basicConfig(filename='log')

    import gevent.pywsgi
    gevent.pywsgi.WSGIServer(('', 1000), application=application).serve_forever()
