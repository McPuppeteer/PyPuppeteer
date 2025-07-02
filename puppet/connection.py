import asyncio
import struct
import json
import uuid
import socket
import enum
import nbtlib
from traceback import print_stack

from .constants import *
from io import BytesIO


def _setup_broadcast_listener(mcast_grp: str | None = None):
    """
    Set up a non-blocking UDP socket for broadcast or multicast listening.

    :param mcast_grp Optional multicast group IP address to join.
    :return: Configured UDP socket.
    :rtype: socket.socket
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', BROADCAST_PORT))

    if mcast_grp:
        # For multicast, join the group
        mreq = socket.inet_aton(mcast_grp) + socket.inet_aton('0.0.0.0')
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return sock


async def gen_broadcasts():
    """
    Asynchronously listen for and yield valid broadcast packets.

    Listens for UDP packets on the broadcast port. Yields decoded JSON
    objects and their source addresses for packets that start with the
    expected magic number.

    :yield: Tuple of (info, addr), where info is the decoded JSON object
            and addr is the sender's address.
    :rtype: AsyncGenerator[Tuple[dict, Tuple[str, int]], None]
    """
    loop = asyncio.get_running_loop()
    sock = _setup_broadcast_listener()

    while True:
        data, addr = await loop.sock_recvfrom(sock, 1024)

        if not data.startswith(BROADCAST_MAGIC_NUMBER):
            continue
        data = data[len(BROADCAST_MAGIC_NUMBER):]
        try:
            info = json.loads(data.decode())
            yield info, addr
        except Exception:
            continue  # Ignore invalid packets


class PuppeteerError(Exception):
    """ 
    The generic error class for anything bad that happens around the server.
    Mostly server side or connection issues.
    """
    type: PuppeteerErrorType

    def __init__(self, msg: str, etype: PuppeteerErrorType = PuppeteerErrorType.UNKNOWN_ERROR):
        self.type = etype
        super().__init__(msg)


class ClientConnection:
    """
    Represents a connection to a Minecraft client using the Puppeteer protocol.
    Handles connection setup, packet sending, and response handling.
    """

    running: bool = False
    callback_handler = None

    global_error_handler = None

    port: int
    host: str

    def handle_error(self, err):
        if self.global_error_handler is not None:
            if not self.global_error_handler(err):
                return

        for _, future in self.promises.items():
            if not future.done():
                future.set_exception(err)
        print("Killing server due to fatal error: \n" + str(err))

        return True

    async def _listen_for_data(self):
        """ Runs in the background listening for callbacks and data """

        assert self.running
        try:
            while self.running:
                header = await self.reader.readexactly(1 + 4)
                packet_type, length = struct.unpack("!ci", header)

                buffer = await self.reader.readexactly(length)

                # Handle json
                if packet_type == b'j':
                    info = json.loads(buffer.decode("utf-8"))
                    assert type(info) is dict

                    if info.get("callback", False):

                        if self.callback_handler is not None:
                            await self.callback_handler(info)

                        continue
                    if not "id" in info:
                        if self.handle_error(
                                PuppeteerError(
                                    "GLOBAL ERROR: " + info.get("message", "UNSPECIFIED ERROR"),
                                    etype=str2error(info.get("type")))
                        ):
                            return
                    if not info["id"] in self.promises:
                        if self.handle_error(PuppeteerError("GLOBAL ERROR: Unknown id returned"), FORMAT_ERROR):
                            return

                    pro = self.promises[info["id"]]

                    pro.set_result((packet_type[0], info))

                    del self.promises[info["id"]]
                elif packet_type == b'n' or packet_type == b'b':
                    idlen = struct.unpack("!h", await self.reader.readexactly(2))[0]
                    id = (await self.reader.readexactly(idlen)).decode("utf-8")

                    
                    if not id in self.promises:
                        if self.handle_error(PuppeteerError("GLOBAL ERROR: Unknown id returned"), FORMAT_ERROR):
                            return
                    pro = self.promises[id]


                    if packet_type == b'b':
                        pro.set_result((packet_type[0], buffer))
                    else:
                        reader = BytesIO(buffer)
                        # Minecraft sends the first byte to specify what we are getting
                        tag_type = reader.read(1)[0]

                        cls = nbtlib.Base.all_tags.get(tag_type)

                        if cls is None:
                            if self.handle_error(PuppeteerError("GLOBAL ERROR: Nbt tag id: " + hex(tag_type)),
                                FORMAT_ERROR):
                                return
                        
                        tag = cls.parse(reader)
                        pro.set_result((packet_type[0], tag))
                    

                    del self.promises[id]
                else:
                    if self.handle_error(PuppeteerError("GLOBAL ERROR: Unknown packet type: " + hex(packet_type[0])),
                                         FORMAT_ERROR):
                        return
        except Exception as e:
            print_stack(e)
            
        finally:
            for _, future in self.promises.items():
                if not future.done():
                    future.set_exception(
                        PuppeteerError("Killed server", etype=SERVER_KILLED)
                    )

    async def write_packet(self, cmd: str, extra: dict | None = None) -> tuple[int, dict | bytes | nbtlib.Base]:
        """
        Sends a JSON packet to the server.

        :param cmd: Command string to specify what command is being used
        :param extra: Extra JSON data to be sent along

        :return: Coroutine that yields a tuple, the first being an int representing the datatype, and the second being that datatype
        """

        assert self.running

        loop = asyncio.get_running_loop()
        fut = loop.create_future()

        pid = str(uuid.uuid4())

        self.promises[pid] = fut

        if extra is None:
            extra = {}

        packet = {"cmd": cmd, "id": pid, **extra}
        data = json.dumps(packet).encode("utf-8")

        data = struct.pack("!ci", b'j', len(data)) + data

        self.writer.write(data)
        await self.writer.drain()

        return await fut

    @classmethod
    async def discover_client(cls):
        """
        Used UDP broadcast sent by the Minecraft client mod to
        discover the first available client. 
        
        **NOTE:**
        If multiple clients are running, the choice
        will be up to chance.

        **NOTE:**
        It is possible for this to wait forever if nothing is
        ever found

        :return: A coroutine that yields a new ClientConnection
        :rtype: Awaitable[ClientConnection]
        """

        broadcast_itr = gen_broadcasts()
        broadcast, (host, port) = await anext(broadcast_itr)

        return cls(host, broadcast["port"])

    def __init__(self, host: str, port: int):
        """ 
        Create the python object, 
        <b> BUT YOU MUST FIRST CALL start() BEFORE YOU CAN DO ANYTHING </b>

        :param host: An ip to connect too
        :param port: The port to connect too
        """

        self.port = port
        self.host = host

    async def start(self):
        """
        This is required to actually do anything. It actually connects
        to the Minecraft client

        :return: nothing
        :rtype: Awaitable[None]
        """

        self.running = True

        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.promises = dict()

        self.listener = asyncio.create_task(self._listen_for_data())

    async def close(self):
        """
        Close the connection, and the listener coroutine

        :return: nothing
        :rtype: Awaitable[None]
        """

        self.running = False
        self.listener.cancel()

    async def __aenter__(self):
        if not self.running:
            await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
