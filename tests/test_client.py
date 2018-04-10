import asyncio
import reprlib
from enum import Enum, unique

from asynctest import TestCase, mock

from aiocometd.client import Client
from aiocometd.exceptions import ServerError, ClientInvalidOperation, \
    TransportError, TransportTimeoutError, ClientError
from aiocometd.transport import DEFAULT_CONNECTION_TYPE, ConnectionType


@unique
class MockConnectionType(Enum):
    TYPE1 = "type1"
    TYPE2 = "type2"
    TYPE3 = "type3"
    TYPE4 = "type4"


class TestClient(TestCase):
    def setUp(self):
        self.client = Client("")

    async def long_task(self, result, timeout=None):
        if timeout:
            await asyncio.sleep(timeout, loop=self.loop)
        if not isinstance(result, Exception):
            return result
        else:
            raise result

    def test_init_with_loop(self):
        loop = object()

        client = Client(endpoint=None, loop=loop)

        self.assertIs(client._loop, loop)

    @mock.patch("aiocometd.client.asyncio")
    def test_init_without_loop(self, asyncio_mock):
        loop = object()
        asyncio_mock.get_event_loop.return_value = loop

        client = Client(endpoint=None)

        self.assertIs(client._loop, loop)

    def test_init_with_no_connection_types(self):
        with self.assertLogs("aiocometd.client", "DEBUG") as log:
            client = Client(endpoint=None)

        self.assertEqual(client._connection_types,
                         [ConnectionType.WEBSOCKET,
                          ConnectionType.LONG_POLLING])
        connection_type_strings = [ct.value for ct in
                                   client._connection_types]
        log_fmt_spec = "DEBUG:aiocometd.client:" \
                       "Created client with connection_types: {!r}"
        self.assertEqual(log.output,
                         [log_fmt_spec.format(connection_type_strings)])

    def test_init_with_connection_types_list(self):
        list = [ConnectionType.LONG_POLLING, ConnectionType.WEBSOCKET]

        with self.assertLogs("aiocometd.client", "DEBUG") as log:
            client = Client(endpoint=None, connection_types=list)

        self.assertEqual(client._connection_types, list)
        connection_type_strings = [ct.value for ct in
                                   client._connection_types]
        log_fmt_spec = "DEBUG:aiocometd.client:" \
                       "Created client with connection_types: {!r}"
        self.assertEqual(log.output,
                         [log_fmt_spec.format(connection_type_strings)])

    def test_init_with_connection_type_value(self):
        type = ConnectionType.LONG_POLLING

        with self.assertLogs("aiocometd.client", "DEBUG") as log:
            client = Client(endpoint=None, connection_types=type)

        self.assertEqual(client._connection_types, [type])
        connection_type_strings = [ct.value for ct in
                                   client._connection_types]
        log_fmt_spec = "DEBUG:aiocometd.client:" \
                       "Created client with connection_types: {!r}"
        self.assertEqual(log.output,
                         [log_fmt_spec.format(connection_type_strings)])

    def test_subscriptions(self):
        self.client._transport = mock.MagicMock()
        self.client._transport.subscriptions = {"channel1", "channel2"}

        result = self.client.subscriptions

        self.assertEqual(result, self.client._transport.subscriptions)

    def test_subscriptions_emtpy_on_none_transport(self):
        self.client._transport = None

        result = self.client.subscriptions

        self.assertEqual(result, set())

    def test_connection_type(self):
        self.client._transport = mock.MagicMock()
        self.client._transport.connection_type = object()

        result = self.client.connection_type

        self.assertIs(result, self.client._transport.connection_type)

    def test_connection_type_none_on_no_transport(self):
        self.assertIsNone(self.client.connection_type)

    def test_closed(self):
        self.assertIs(self.client.closed, self.client._closed)

    def test_closed_read_only(self):
        with self.assertRaises(AttributeError):
            self.client.closed = False

    @mock.patch("aiocometd.client.ConnectionType", new=MockConnectionType)
    def test_pick_connection_type(self):
        self.client._connection_types = [
            MockConnectionType.TYPE1,
            MockConnectionType.TYPE2,
            MockConnectionType.TYPE3
        ]
        supported_types = [
            MockConnectionType.TYPE2.value,
            MockConnectionType.TYPE3.value,
            MockConnectionType.TYPE4.value
        ]

        result = self.client._pick_connection_type(supported_types)

        self.assertEqual(result, MockConnectionType.TYPE2)

    @mock.patch("aiocometd.client.ConnectionType", new=MockConnectionType)
    def test_pick_connection_type_without_overlap(self):
        self.client._connection_types = [
            MockConnectionType.TYPE1,
            MockConnectionType.TYPE2
        ]
        supported_types = [
            MockConnectionType.TYPE3.value,
            MockConnectionType.TYPE4.value
        ]

        result = self.client._pick_connection_type(supported_types)

        self.assertIsNone(result)

    @mock.patch("aiocometd.client.create_transport")
    async def test_negotiate_transport_default(self, create_transport):
        response = {
            "supportedConnectionTypes": [DEFAULT_CONNECTION_TYPE.value],
            "successful": True
        }
        transport = mock.MagicMock()
        transport.connection_type = DEFAULT_CONNECTION_TYPE
        transport.handshake = mock.CoroutineMock(return_value=response)
        create_transport.return_value = transport
        self.client._pick_connection_type = \
            mock.MagicMock(return_value=DEFAULT_CONNECTION_TYPE)
        self.client._verify_response = mock.MagicMock()

        with self.assertLogs("aiocometd.client", "DEBUG") as log:
            result = await self.client._negotiate_transport()

        self.assertEqual(result, transport)
        create_transport.assert_called_with(
            DEFAULT_CONNECTION_TYPE,
            endpoint=self.client.endpoint,
            incoming_queue=self.client._incoming_queue,
            ssl=self.client.ssl)
        transport.handshake.assert_called_with(self.client._connection_types)
        self.client._verify_response.assert_called_with(response)
        self.client._pick_connection_type.assert_called_with(
            response["supportedConnectionTypes"])
        log_prefix = "DEBUG:aiocometd.client:"
        log_message1 = (log_prefix +
                        "Connection types supported by the server: {!r}"
                        .format(response["supportedConnectionTypes"]))
        log_message2 = (log_prefix +
                        "Picked connection type: {!r}"
                        .format(DEFAULT_CONNECTION_TYPE.value))
        self.assertEqual(log.output, [log_message1, log_message2])

    @mock.patch("aiocometd.client.create_transport")
    async def test_negotiate_transport_error(self, create_transport):
        response = {
            "supportedConnectionTypes": [DEFAULT_CONNECTION_TYPE.value],
            "successful": True
        }
        transport = mock.MagicMock()
        transport.connection_type = DEFAULT_CONNECTION_TYPE
        transport.handshake = mock.CoroutineMock(return_value=response)
        transport.close = mock.CoroutineMock()
        create_transport.return_value = transport
        self.client._pick_connection_type = \
            mock.MagicMock(return_value=None)

        with self.assertRaises(ClientError,
                               msg="None of the connection types offered "
                                   "by the server are supported."):
            with self.assertLogs("aiocometd.client", "DEBUG") as log:
                await self.client._negotiate_transport()

        create_transport.assert_called_with(
            DEFAULT_CONNECTION_TYPE,
            endpoint=self.client.endpoint,
            incoming_queue=self.client._incoming_queue,
            ssl=self.client.ssl)
        transport.handshake.assert_called_with(self.client._connection_types)
        self.client._pick_connection_type.assert_called_with(
            response["supportedConnectionTypes"])
        transport.close.assert_called()
        log_prefix = "DEBUG:aiocometd.client:"
        log_message1 = (log_prefix +
                        "Connection types supported by the server: {!r}"
                        .format(response["supportedConnectionTypes"]))
        self.assertEqual(log.output, [log_message1])

    @mock.patch("aiocometd.client.create_transport")
    async def test_negotiate_transport_non_default(self, create_transport):
        non_default_type = ConnectionType.WEBSOCKET
        self.client._connection_types = [non_default_type]
        response = {
            "supportedConnectionTypes": [DEFAULT_CONNECTION_TYPE.value,
                                         non_default_type.value],
            "successful": True
        }
        transport1 = mock.MagicMock()
        transport1.connection_type = DEFAULT_CONNECTION_TYPE
        transport1.client_id = "client_id"
        transport1.handshake = mock.CoroutineMock(return_value=response)
        transport1.close = mock.CoroutineMock()
        transport2 = mock.MagicMock()
        transport2.connection_type = non_default_type
        transport2.client_id = None
        create_transport.side_effect = [transport1, transport2]
        self.client._pick_connection_type = \
            mock.MagicMock(return_value=non_default_type)
        self.client._verify_response = mock.MagicMock()

        with self.assertLogs("aiocometd.client", "DEBUG") as log:
            result = await self.client._negotiate_transport()

        self.assertEqual(result, transport2)
        create_transport.assert_has_calls(
            [
                mock.call(
                    DEFAULT_CONNECTION_TYPE,
                    endpoint=self.client.endpoint,
                    incoming_queue=self.client._incoming_queue,
                    ssl=self.client.ssl),
                mock.call(
                    non_default_type,
                    endpoint=self.client.endpoint,
                    incoming_queue=self.client._incoming_queue,
                    client_id=transport1.client_id,
                    ssl=self.client.ssl)
            ]
        )
        transport1.handshake.assert_called_with(self.client._connection_types)
        self.client._verify_response.assert_called_with(response)
        self.client._pick_connection_type.assert_called_with(
            response["supportedConnectionTypes"])
        transport1.close.assert_called()
        log_prefix = "DEBUG:aiocometd.client:"
        log_message1 = (log_prefix +
                        "Connection types supported by the server: {!r}"
                        .format(response["supportedConnectionTypes"]))
        log_message2 = (log_prefix +
                        "Picked connection type: {!r}"
                        .format(non_default_type.value))
        self.assertEqual(log.output, [log_message1, log_message2])

    async def test_open(self):
        transport = mock.MagicMock()
        connect_result = object()
        transport.connect = mock.CoroutineMock(return_value=connect_result)
        self.client._negotiate_transport = mock.CoroutineMock(
            return_value=transport
        )
        self.client._verify_response = mock.MagicMock()
        self.client._closed = True

        await self.client.open()

        self.client._negotiate_transport.assert_called()
        transport.connect.assert_called()
        self.client._verify_response.assert_called_with(connect_result)

    async def test_open_if_already_open(self):
        transport = mock.MagicMock()
        connect_result = object()
        transport.connect = mock.CoroutineMock(return_value=connect_result)
        self.client._negotiate_transport = mock.CoroutineMock(
            return_value=transport
        )
        self.client._verify_response = mock.MagicMock()
        self.client._closed = False

        with self.assertRaises(ClientInvalidOperation,
                               msg="Client is already open."):
            await self.client.open()

        self.client._negotiate_transport.assert_not_called()
        transport.connect.assert_not_called()
        self.client._verify_response.assert_not_called()

    async def test_close(self):
        self.client._closed = False
        self.client._transport = mock.MagicMock()
        self.client._transport.client_id = "client_id"
        self.client._transport.disconnect = mock.CoroutineMock()
        self.client._transport.close = mock.CoroutineMock()

        await self.client.close()

        self.client._transport.disconnect.assert_called()
        self.client._transport.close.assert_called()
        self.assertTrue(self.client.closed)

    async def test_close_no_client_id(self):
        self.client._closed = False
        self.client._transport = mock.MagicMock()
        self.client._transport.client_id = None
        self.client._transport.disconnect = mock.CoroutineMock()
        self.client._transport.close = mock.CoroutineMock()

        await self.client.close()

        self.client._transport.disconnect.assert_not_called()
        self.client._transport.close.assert_called()
        self.assertTrue(self.client.closed)

    async def test_close_if_already_closed(self):
        self.client._closed = True
        self.client._transport = mock.MagicMock()
        self.client._transport.client_id = "client_id"
        self.client._transport.disconnect = mock.CoroutineMock()
        self.client._transport.close = mock.CoroutineMock()

        await self.client.close()

        self.client._transport.disconnect.assert_called()
        self.client._transport.close.assert_called()
        self.assertTrue(self.client.closed)

    async def test_close_on_transport_error(self):
        self.client._closed = False
        self.client._transport = mock.MagicMock()
        self.client._transport.client_id = "client_id"
        error = TransportError("description")
        self.client._transport.disconnect = mock.CoroutineMock(
            side_effect=error
        )
        self.client._transport.close = mock.CoroutineMock()
        expected_log = ["DEBUG:aiocometd.client:"
                        "Disconnect request failed, {}".format(error)]

        with self.assertLogs("aiocometd.client", "DEBUG") as log:
            await self.client.close()

        self.assertEqual(log.output, expected_log)
        self.client._transport.disconnect.assert_called()
        self.client._transport.close.assert_called()
        self.assertTrue(self.client.closed)

    async def test_subscribe(self):
        response = {
            "channel": "/meta/subscribe",
            "successful": True,
            "subscription": "channel1",
            "id": "1"
        }
        self.client._transport = mock.MagicMock()
        self.client._transport.subscribe = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False

        await self.client.subscribe("channel1")

        self.client._transport.subscribe.assert_called_with("channel1")

    async def test_subscribe_on_closed(self):
        self.client._closed = True

        with self.assertRaises(ClientInvalidOperation,
                               msg="Can't send subscribe request while, "
                                   "the client is closed."):
            await self.client.subscribe("channel1")

    async def test_subscribe_error(self):
        response = {
            "channel": "/meta/subscribe",
            "successful": False,
            "subscription": "channel1",
            "id": "1"
        }
        self.client._transport = mock.MagicMock()
        self.client._transport.subscribe = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False
        error = ServerError("Subscribe request failed.", response)

        with self.assertRaises(ServerError, msg=str(error)):
            await self.client.subscribe("channel1")

        self.client._transport.subscribe.assert_called_with("channel1")

    async def test_unsubscribe(self):
        response = {
            "channel": "/meta/unsubscribe",
            "successful": True,
            "subscription": "channel1",
            "id": "1"
        }
        self.client._transport = mock.MagicMock()
        self.client._transport.unsubscribe = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False

        await self.client.unsubscribe("channel1")

        self.client._transport.unsubscribe.assert_called_with("channel1")

    async def test_unsubscribe_on_closed(self):
        self.client._closed = True

        with self.assertRaises(ClientInvalidOperation,
                               msg="Can't send unsubscribe request while, "
                                   "the client is closed."):
            await self.client.unsubscribe("channel1")

    async def test_unsubscribe_error(self):
        response = {
            "channel": "/meta/unsubscribe",
            "successful": False,
            "subscription": "channel1",
            "id": "1"
        }
        self.client._transport = mock.MagicMock()
        self.client._transport.unsubscribe = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False
        error = ServerError("Unsubscribe request failed.", response)

        with self.assertRaises(ServerError, msg=str(error)):
            await self.client.unsubscribe("channel1")

        self.client._transport.unsubscribe.assert_called_with("channel1")

    async def test_publish(self):
        response = {
            "channel": "/channel1",
            "successful": True,
            "id": "1"
        }
        data = {}
        self.client._transport = mock.MagicMock()
        self.client._transport.publish = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False

        await self.client.publish("channel1", data)

        self.client._transport.publish.assert_called_with("channel1", data)

    async def test_publish_on_closed(self):
        self.client._closed = True

        with self.assertRaises(ClientInvalidOperation,
                               msg="Can't publish data while, "
                                   "the client is closed."):
            await self.client.publish("channel1", {})

    async def test_publish_error(self):
        response = {
            "channel": "/channel1",
            "successful": False,
            "id": "1"
        }
        data = {}
        self.client._transport = mock.MagicMock()
        self.client._transport.publish = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False
        error = ServerError("Publish request failed.", response)

        with self.assertRaises(ServerError, msg=str(error)):
            await self.client.publish("channel1", data)

        self.client._transport.publish.assert_called_with("channel1", data)

    def test_repr(self):
        self.client.endpoint = "http://example.com"
        expected = "Client({}, {}, connection_timeout={}, ssl={}, " \
                   "prefetch_size={}, loop={})".format(
            reprlib.repr(self.client.endpoint),
            reprlib.repr(self.client._connection_types),
            reprlib.repr(self.client.connection_timeout),
            reprlib.repr(self.client.ssl),
            reprlib.repr(self.client._prefetch_size),
            reprlib.repr(self.client._loop)
        )

        result = repr(self.client)
        print(result)

        self.assertEqual(result, expected)

    def test_verify_response_on_success(self):
        self.client._raise_server_error = mock.MagicMock()
        response = {
            "channel": "/channel1",
            "successful": True,
            "id": "1"
        }

        self.client._verify_response(response)

        self.client._raise_server_error.assert_not_called()

    def test_verify_response_on_error(self):
        self.client._raise_server_error = mock.MagicMock()
        response = {
            "channel": "/channel1",
            "successful": False,
            "id": "1"
        }

        self.client._verify_response(response)

        self.client._raise_server_error.assert_called_with(response)

    def test_verify_response_no_successful_status(self):
        self.client._raise_server_error = mock.MagicMock()
        response = {
            "channel": "/channel1",
            "id": "1"
        }

        self.client._verify_response(response)

        self.client._raise_server_error.assert_not_called()

    def test_raise_server_error_meta(self):
        response = {
            "channel": "/meta/subscribe",
            "successful": False,
            "id": "1"
        }
        error_message = \
            type(self.client)._SERVER_ERROR_MESSAGES[response["channel"]]

        with self.assertRaises(ServerError, msg=error_message):
            self.client._raise_server_error(response)

    def test_raise_server_error_service(self):
        response = {
            "channel": "/service/test",
            "successful": False,
            "id": "1"
        }

        with self.assertRaises(
                ServerError,
                msg="Service request failed."):
            self.client._raise_server_error(response)

    def test_raise_server_error_publish(self):
        response = {
            "channel": "/some/channel",
            "successful": False,
            "id": "1"
        }

        with self.assertRaises(
                ServerError,
                msg="Publish request failed."):
            self.client._raise_server_error(response)

    async def test_pending_count(self):
        self.client._incoming_queue = asyncio.Queue()
        await self.client._incoming_queue.put(1)
        await self.client._incoming_queue.put(2)

        self.assertEqual(self.client.pending_count, 2)

    async def test_pending_count_if_none_queue(self):
        self.client._incoming_queue = None

        self.assertEqual(self.client.pending_count, 0)

    async def test_has_pending_messages(self):
        self.client._incoming_queue = asyncio.Queue()
        await self.client._incoming_queue.put(1)

        self.assertTrue(self.client.has_pending_messages)

    async def test_has_pending_messages_false(self):
        self.client._incoming_queue = None

        self.assertFalse(self.client.has_pending_messages)

    async def test_receive_on_closed(self):
        self.client._closed = True
        self.client._incoming_queue = None

        with self.assertRaises(ClientInvalidOperation,
                               msg="The client is closed and there are "
                                   "no pending messages."):
            await self.client.receive()

    async def test_receive_on_closed_and_pending_messages(self):
        self.client._closed = True
        response = {
            "channel": "/channel1",
            "data": {},
            "id": "1"
        }
        self.client._incoming_queue = mock.MagicMock()
        self.client._incoming_queue.qsize.return_value = 1
        self.client._get_message = mock.CoroutineMock(return_value=response)
        self.client._verify_response = mock.MagicMock()

        result = await self.client.receive()

        self.assertEqual(result, response)
        self.client._get_message.assert_called_with(
            self.client.connection_timeout)
        self.client._verify_response.assert_called_with(response)

    async def test_receive_on_open(self):
        self.client._closed = False
        response = {
            "channel": "/channel1",
            "data": {},
            "id": "1"
        }
        self.client._incoming_queue = mock.MagicMock()
        self.client._incoming_queue.qsize.return_value = 1
        self.client._get_message = mock.CoroutineMock(return_value=response)
        self.client._verify_response = mock.MagicMock()

        result = await self.client.receive()

        self.assertEqual(result, response)
        self.client._get_message.assert_called_with(
            self.client.connection_timeout)
        self.client._verify_response.assert_called_with(response)

    async def test_receive_on_connection_timeout(self):
        self.client._closed = True
        self.client._incoming_queue = mock.MagicMock()
        self.client._incoming_queue.qsize.return_value = 1
        self.client._get_message = mock.CoroutineMock(
            side_effect=TransportTimeoutError())
        self.client._verify_response = mock.MagicMock()

        with self.assertRaises(TransportTimeoutError):
            await self.client.receive()

        self.client._get_message.assert_called_with(
            self.client.connection_timeout)
        self.client._verify_response.assert_not_called()

    async def test_aiter(self):
        responses = [
            {
                "channel": "/channel1",
                "data": {},
                "id": "1"
            },
            {
                "channel": "/channel2",
                "data": {},
                "id": "2"
            }
        ]
        self.client.receive = mock.CoroutineMock(
            side_effect=responses + [ClientInvalidOperation()])

        result = []
        async for message in self.client:
            result.append(message)

        self.assertEqual(result, responses)

    async def test_context_manager(self):
        self.client.open = mock.CoroutineMock()
        self.client.close = mock.CoroutineMock()

        async with self.client as client:
            pass

        self.assertIs(client, self.client)
        self.client.open.assert_called()
        self.client.close.assert_called()

    async def test_context_manager_on_enter_error(self):
        self.client.open = mock.CoroutineMock(
            side_effect=TransportError()
        )
        self.client.close = mock.CoroutineMock()

        with self.assertRaises(TransportError):
            async with self.client:
                pass

        self.client.open.assert_called()
        self.client.close.assert_called()

    @mock.patch("aiocometd.client.asyncio")
    async def test_wait_connection_timeout_on_timeout(self, asyncio_mock):
        self.client._transport = mock.MagicMock()
        self.client._transport.wait_for_connecting = mock.CoroutineMock()
        self.client._transport.wait_for_connected = mock.MagicMock(
            return_value=object()
        )
        timeout = 2
        asyncio_mock.wait_for = mock.CoroutineMock(
            side_effect=asyncio.TimeoutError()
        )
        asyncio_mock.TimeoutError = asyncio.TimeoutError

        await self.client._wait_connection_timeout(timeout)

        self.client._transport.wait_for_connecting.assert_called_once()
        self.client._transport.wait_for_connected.assert_called_once()
        asyncio_mock.wait_for.assert_called_with(
            self.client._transport.wait_for_connected.return_value,
            timeout,
            loop=self.client._loop
        )

    @mock.patch("aiocometd.client.asyncio")
    async def test_wait_connection_timeout_iterations(self, asyncio_mock):
        self.client._transport = mock.MagicMock()
        self.client._transport.wait_for_connecting = mock.CoroutineMock()
        self.client._transport.wait_for_connected = mock.MagicMock(
            return_value=object()
        )
        timeout = 2
        asyncio_mock.wait_for = mock.CoroutineMock(
            side_effect=[None, asyncio.TimeoutError()]
        )
        asyncio_mock.TimeoutError = asyncio.TimeoutError

        await self.client._wait_connection_timeout(timeout)

        self.client._transport.wait_for_connecting.assert_has_calls(
            [mock.call()] * 2
        )
        self.client._transport.wait_for_connecting.assert_has_calls(
            [mock.call()] * 2
        )
        asyncio_mock.wait_for.assert_has_calls(
            [mock.call(
                self.client._transport.wait_for_connected.return_value,
                timeout,
                loop=self.client._loop)] * 2
        )

    async def test_get_message_no_timeout(self):
        self.client._incoming_queue = mock.MagicMock()
        self.client._incoming_queue.get = mock.CoroutineMock(
            return_value=object()
        )
        self.client._wait_connection_timeout = mock.CoroutineMock()

        result = await self.client._get_message(None)

        self.assertIs(result, self.client._incoming_queue.get.return_value)
        self.client._wait_connection_timeout.assert_not_called()

    async def test_get_message_with_timeout_not_triggered(self):
        self.client._incoming_queue = mock.MagicMock()
        get_result = object()
        self.client._incoming_queue.get = mock.MagicMock(
            return_value=self.long_task(get_result, timeout=None)
        )
        self.client._wait_connection_timeout = mock.MagicMock(
            return_value=self.long_task(None, timeout=1)
        )
        timeout = 2

        result = await self.client._get_message(timeout)

        self.assertIs(result, get_result)
        self.client._wait_connection_timeout.assert_called_with(timeout)

    async def test_get_message_with_timeout_triggered(self):
        self.client._incoming_queue = mock.MagicMock()
        get_result = object()
        self.client._incoming_queue.get = mock.MagicMock(
            return_value=self.long_task(get_result, timeout=1)
        )
        self.client._wait_connection_timeout = mock.MagicMock(
            return_value=self.long_task(None, timeout=None)
        )
        timeout = 2

        with self.assertRaises(TransportTimeoutError,
                               msg="Lost connection with the server"):
            await self.client._get_message(timeout)

        self.client._wait_connection_timeout.assert_called_with(timeout)

    @mock.patch("aiocometd.client.asyncio")
    async def test_get_message_cancelled(self, asyncio_mock):
        self.client._incoming_queue = mock.MagicMock()
        self.client._wait_connection_timeout = mock.MagicMock()
        asyncio_mock.ensure_future = mock.MagicMock(
            side_effect=[mock.MagicMock(), mock.MagicMock()]
        )
        asyncio_mock.wait = mock.CoroutineMock(
            side_effect=asyncio.CancelledError()
        )
        asyncio_mock.CancelledError = asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await self.client._get_message(1)

        for task in asyncio_mock.ensure_future.side_effect:
            task.cancel.assert_called()