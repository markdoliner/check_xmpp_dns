#!/usr/bin/env python3

# Licensed as follows (this is the 2-clause BSD license, aka
# "Simplified BSD License" or "FreeBSD License"):
#
# Copyright (c) 2011-2014,2019,2022,2024 Mark Doliner
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

import collections.abc
import contextlib
import enum
import logging
import os
import typing
import urllib.parse

# import cgitb; cgitb.enable()
import anyio
import dns.asyncresolver
import dns.exception
import dns.name
import dns.nameserver
import dns.rdata
import dns.rdatatype
import dns.rdtypes.IN.A
import dns.rdtypes.IN.AAAA
import dns.rdtypes.IN.SRV
import dns.resolver
import jinja2
import starlette.applications
import starlette.requests
import starlette.responses
import starlette.routing

_REQUEST_LEDGER_FILENAME_ENV_VAR: typing.Final = "CHECK_XMPP_DNS_REQUEST_LEDGER_FILENAME"
_REQUEST_LEDGER_DEFAULT_FILENAME: typing.Final = "/var/log/check-xmpp-dns/requestledger.txt"

_jinja2_env: jinja2.Environment | None = None

logger: typing.Final = logging.getLogger(__name__)


@enum.unique
class ClientOrServerType(enum.Enum):
    CLIENT = "client"
    SERVER = "server"


@enum.unique
class TlsType(enum.Enum):
    # The normal XMPP ports.
    # These come from either _xmpp-client._tcp.example.com
    # or _xmpp-server._tcp.example.com DNS records.
    STARTTLS = "STARTTLS"

    # Ports that require TLS negotiation immediately upon connecting,
    # as discussed in XEP-0368.
    # These come from either _xmpps-client._tcp.example.com
    # or _xmpps-server._tcp.example.com DNS records.
    DIRECT_TLS = "Direct TLS"


STANDARD_PORTS = {
    (ClientOrServerType.CLIENT, TlsType.STARTTLS): 5222,
    (ClientOrServerType.CLIENT, TlsType.DIRECT_TLS): 5223,
    (ClientOrServerType.SERVER, TlsType.STARTTLS): 5269,
    (ClientOrServerType.SERVER, TlsType.DIRECT_TLS): 5270,
}


class AnswerTuple(typing.NamedTuple):
    answer: dns.resolver.Answer | None
    client_or_server: ClientOrServerType
    tls_type: TlsType


@enum.unique
class NoteType(enum.Enum):
    DIRECT_TLS = enum.auto()
    NON_STANDARD_PORT = enum.auto()
    PORT_REUSED_WITH_BOTH_TYPES_DIFFERENT = enum.auto()
    PORT_REUSED_WITH_DIFFERENT_CLIENT_OR_SERVER_TYPE = enum.auto()
    PORT_REUSED_WITH_DIFFERENT_TLS_TYPE = enum.auto()


class NoteForDisplay(typing.NamedTuple):
    note_type: NoteType
    note: str


class RecordForDisplay(typing.NamedTuple):
    port: int
    priority: int
    target: str
    weight: int
    notes: list[NoteForDisplay]


def _get_jinja2_env() -> jinja2.Environment:
    global _jinja2_env

    if _jinja2_env is None:
        _jinja2_env = jinja2.Environment(
            autoescape=True,
            enable_async=True,
            loader=jinja2.FileSystemLoader("templates"),
            undefined=jinja2.StrictUndefined,
        )
        _jinja2_env.globals = {"NoteType": NoteType}

    return _jinja2_env


async def _append_to_request_ledger(hostname: str) -> None:
    request_ledger_filename = os.environ.get(_REQUEST_LEDGER_FILENAME_ENV_VAR) or _REQUEST_LEDGER_DEFAULT_FILENAME
    async with await anyio.open_file(request_ledger_filename, "a") as f:
        await f.write("%s\n" % urllib.parse.quote(hostname))


def _sort_records_for_display(records: list[RecordForDisplay]) -> list[RecordForDisplay]:
    return sorted(
        records,
        key=lambda record: "%10d %10d %50s %d"
        % (record.priority, 1000000000 - record.weight, record.target, record.port),
    )


def _assert_srv_records(answer: dns.resolver.Answer) -> collections.abc.Iterator[dns.rdtypes.IN.SRV.SRV]:
    """Return an iterator through the Answer's records, asserting that they're all SRV records."""
    for record in answer:
        if not isinstance(record, dns.rdtypes.IN.SRV.SRV):
            message = f"record type should have been dns.rdtypes.IN.SRV.SRV but was {type(record)}"
            raise AssertionError(message)
        yield record


def _build_records_for_display(
    answers_list: list[AnswerTuple], client_or_server: ClientOrServerType
) -> tuple[list[RecordForDisplay], dict[NoteType, int]]:
    records_for_display = list[RecordForDisplay]()

    for answers in answers_list:
        if answers.client_or_server == client_or_server and answers.answer is not None:
            for record in _assert_srv_records(answers.answer):
                records_for_display.append(_build_record_for_display(record, answers, answers_list))

    sorted_records_for_display = _sort_records_for_display(records_for_display)

    # dict is used here rather than set so that order is preserved.
    # (As of Python 3.7 according to https://stackoverflow.com/a/39980744/1634007)
    note_types_used_by_these_records = {
        note.note_type: None for record in sorted_records_for_display for note in record.notes
    }
    note_types_to_footnote_indexes = {
        note_type: index + 1 for index, note_type in enumerate(note_types_used_by_these_records)
    }

    return (
        sorted_records_for_display,
        note_types_to_footnote_indexes,
    )


def _has_record_for_host_and_port(answers: AnswerTuple, target: dns.name.Name, port: int) -> bool:
    """Return True if any record in `answers` points to the given
    `target` and `port`.
    """
    return answers.answer is not None and any(
        record.target == target and record.port == port for record in _assert_srv_records(answers.answer)
    )


def _build_record_for_display(
    record: dns.rdtypes.IN.SRV.SRV,
    answers: AnswerTuple,
    answers_list: list[AnswerTuple],
) -> RecordForDisplay:
    notes = list[NoteForDisplay]()

    if answers.tls_type == TlsType.DIRECT_TLS:
        notes.append(NoteForDisplay(NoteType.DIRECT_TLS, "This is a Direct TLS port."))

    # This note isn't displayed for Direct TLS ports because
    # Direct TLS isn't formally standardized so there is no
    # standard port (though, yes, historically 5223 has been
    # used for client connections and 5270 has been used for
    # server connections).
    standard_port = STANDARD_PORTS[(answers.client_or_server, answers.tls_type)]
    if answers.tls_type == TlsType.STARTTLS and record.port != standard_port:
        notes.append(NoteForDisplay(NoteType.NON_STANDARD_PORT, "Non-standard port."))

    # Look for the same hostname and port in the responses from the
    # other queries.
    for other_answers in answers_list:
        if other_answers == answers:
            # This is the same set of answers that this record came
            # from. No need to check for collisions.
            continue

        if _has_record_for_host_and_port(other_answers, record.target, record.port):
            if other_answers.client_or_server == answers.client_or_server:
                note_type = NoteType.PORT_REUSED_WITH_DIFFERENT_TLS_TYPE
            elif other_answers.tls_type == answers.tls_type:
                note_type = NoteType.PORT_REUSED_WITH_DIFFERENT_CLIENT_OR_SERVER_TYPE
            else:
                note_type = NoteType.PORT_REUSED_WITH_BOTH_TYPES_DIFFERENT
            notes.append(
                NoteForDisplay(
                    note_type,
                    f"This host+port is also advertised as a {other_answers.tls_type.value} "
                    f"record for {other_answers.client_or_server.value}s.",
                )
            )

    return RecordForDisplay(
        port=record.port,
        priority=record.priority,
        # Remove the trailing period for display.
        target=str(record.target).rstrip("."),
        weight=record.weight,
        notes=notes,
    )


async def _get_authoritative_name_servers_for_domain(
    domain: str,
) -> collections.abc.Sequence[str | dns.nameserver.Nameserver] | None:
    """Return a list of strings containing IP addresses of the name servers
    that are considered to be authoritative for the given domain.

    This iteratively queries the name server responsible for each piece of the
    FQDN directly, so as to avoid any caching of results.
    """

    # Create a DNS resolver to use for these requests
    dns_resolver = dns.asyncresolver.Resolver()

    # Set a 2.5 second timeout on the resolver
    dns_resolver.lifetime = 2.5

    # Iterate through the pieces of the hostname from broad to narrow. For
    # each piece, ask which name servers are authoritative for the next
    # narrower piece. Note that we don't bother doing this for the broadest
    # piece of the hostname (e.g. 'com' or 'net') because the list of root
    # servers should rarely change and changes shouldn't affect the outcome
    # of these queries.
    pieces = domain.split(".")
    for i in range(len(pieces) - 1, 0, -1):
        broader_domain = ".".join(pieces[i - 1 :])
        try:
            answer = await dns_resolver.resolve(broader_domain, dns.rdatatype.NS)
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

        new_nameservers = list[str]()
        for record in answer:
            if record.rdtype == dns.rdatatype.NS:
                # Got the hostname of a nameserver. Resolve it to an IP.
                # TODO: Don't do this if the nameserver we just queried gave us
                # an additional record that includes the IP.
                try:
                    answer2 = await dns_resolver.resolve(record.to_text())
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
                    if isinstance(record2, (dns.rdtypes.IN.A.A, dns.rdtypes.IN.AAAA.AAAA)):
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


async def _resolve_srv(dns_resolver: dns.asyncresolver.Resolver, qname: str) -> dns.resolver.Answer | None:
    try:
        records = await dns_resolver.resolve(qname, rdtype=dns.rdatatype.SRV)
    except dns.exception.SyntaxError:
        # TODO: Show "invalid hostname" for this
        records = None
    except dns.resolver.NXDOMAIN:
        records = None
    except dns.resolver.NoAnswer:
        # TODO: Show a specific message for this
        records = None
    except dns.resolver.NoNameservers:
        # TODO: Show a specific message for this
        records = None
    except dns.resolver.Timeout:
        # TODO: Show a specific message for this
        records = None
    return records


async def _look_up_records(hostname: str) -> str:
    """Looks up the DNS records for the given hostname and returns a str containing the full HTML
    response body with the results.
    """
    await _append_to_request_ledger(hostname)

    # Sanity check hostname
    if ".." in hostname:
        return await (
            _get_jinja2_env()
            .get_template("index_with_lookup_error.html.jinja")
            .render_async(hostname=hostname, error_message="Invalid hostname")
        )

    # Look up the list of authoritative name servers for this domain and query
    # them directly when looking up XMPP SRV records. We do this to avoid any
    # potential caching from intermediate name servers.
    authoritative_nameservers = await _get_authoritative_name_servers_for_domain(hostname)
    if not authoritative_nameservers:
        # Could not determine authoritative name servers for domain.
        return await (
            _get_jinja2_env()
            .get_template("index_with_lookup_error.html.jinja")
            .render_async(
                hostname=hostname, error_message="Could not determine the authoritative name servers for this domain."
            )
        )

    # Create a DNS resolver to use for this request
    dns_resolver = dns.asyncresolver.Resolver()

    # Set a 2.5 second timeout on the resolver
    dns_resolver.lifetime = 2.5

    dns_resolver.nameservers = authoritative_nameservers

    # Look up records using four queries.
    answers = list[AnswerTuple]()
    answers.append(
        AnswerTuple(
            await _resolve_srv(dns_resolver, "_xmpp-client._tcp.%s" % hostname),
            ClientOrServerType.CLIENT,
            TlsType.STARTTLS,
        )
    )
    answers.append(
        AnswerTuple(
            await _resolve_srv(dns_resolver, "_xmpps-client._tcp.%s" % hostname),
            ClientOrServerType.CLIENT,
            TlsType.DIRECT_TLS,
        )
    )
    answers.append(
        AnswerTuple(
            await _resolve_srv(dns_resolver, "_xmpp-server._tcp.%s" % hostname),
            ClientOrServerType.SERVER,
            TlsType.STARTTLS,
        )
    )
    answers.append(
        AnswerTuple(
            await _resolve_srv(dns_resolver, "_xmpps-server._tcp.%s" % hostname),
            ClientOrServerType.SERVER,
            TlsType.DIRECT_TLS,
        )
    )

    # Convert the DNS responses into data that's easier to insert
    # into a template.
    (
        client_records_for_display,
        client_record_note_types_to_footnote_indexes,
    ) = _build_records_for_display(answers, ClientOrServerType.CLIENT)
    (
        server_records_for_display,
        server_record_note_types_to_footnote_indexes,
    ) = _build_records_for_display(answers, ClientOrServerType.SERVER)

    # Render the template.
    return await (
        _get_jinja2_env()
        .get_template("index_with_successful_lookup.html.jinja")
        .render_async(
            hostname=hostname,
            client_records=client_records_for_display,
            client_record_note_types_to_footnote_indexes=client_record_note_types_to_footnote_indexes,
            server_records=server_records_for_display,
            server_record_note_types_to_footnote_indexes=server_record_note_types_to_footnote_indexes,
        )
    )


async def _handle_root(request: starlette.requests.Request) -> starlette.responses.HTMLResponse:
    try:
        hostname = request.query_params.get("h")
        if hostname:
            response_body = await _look_up_records(hostname)
        else:
            response_body = await _get_jinja2_env().get_template("index_base.html.jinja").render_async(hostname="")

        return starlette.responses.HTMLResponse(response_body, headers={"Cache-Control": "no-cache"})
    except Exception:
        logger.exception("Unknown error handling request.")
        raise


@contextlib.asynccontextmanager
async def _lifespan(_app: starlette.applications.Starlette) -> collections.abc.AsyncGenerator[None, None]:
    logging.basicConfig(level="INFO")

    # Initialize the jinja2_env global.
    _get_jinja2_env()

    yield


def application() -> starlette.applications.Starlette:
    return starlette.applications.Starlette(
        lifespan=_lifespan,
        routes=[
            starlette.routing.Route("/", _handle_root),
        ],
    )
