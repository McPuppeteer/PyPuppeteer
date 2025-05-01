import asyncio
import struct
import json
import uuid
import socket

BROADCAST_PORT = 43842
BROADCAST_MAGIC_NUMBER = b"PUPPETEER"

def _setup_broadcast_listener(mcast_grp=None):
    """
    Set up a non-blocking UDP socket for broadcast or multicast listening.

    :param mcast_grp: Optional multicast group IP address to join.
    :type mcast_grp: Optional[str]
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
async def getBroadcasts():
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
    pass


class ClientConnection:
    """
    Represents a connection to a Minecraft client using the Puppeteer protocol.
    Handles connection setup, packet sending, and response handling.
    """


    running : bool = False
    callback_handler = None

    port : int
    host : str


    async def _listen_for_data(self):
        """ Runs in the background listening for callbacks and data """

        assert self.running
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
                        self.callback_handler(info)
                    continue
                if not "id" in info:
                    raise PuppeteerError("GLOBAL ERROR: Unknown error has occured in the Minecraft client: " + info.get("message", "UNSPECIFIED ERROR"))
                if not info["id"] in self.promises:
                    raise PuppeteerError("GLOBAL ERROR: Unknown id returned")
                pro = self.promises[info["id"]]
                
                pro.set_result((packet_type[0], info))

                del self.promises[info["id"]]
    async def write_packet(self, cmd, extra=None):
        """
        Sends a JSON packet to the server.

        :param cmd: Command string to specify what command is being used
        :type cmd: str
        :param extra: Extra JSON data to be sent along
        :type extra: Optional[dict]
        :return: Coroutine that yields whatever the server might send back in response
        :rtype: Awaitable[dict]
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
        
        <b>NOTE:</b>
        If multiple clients are running, the choice
        will be up to chance.

        <b>NOTE:</b>
        It is possible for this to wait forever if nothing is
        ever found

        :return: A coroutine that yields a new ClientConnection
        :rtype: Awaitable[ClientConnection]
        """


        broadcast_itr = getBroadcasts()
        broadcast, (host, port) = await anext(broadcast_itr)

        
        return cls(host, broadcast["port"])
    def __init__(self, host, port):
        """ 
        Create the python object, 
        <b> BUT YOU MUST FIRST CALL start() BEFORE YOU CAN DO ANYTHING </b>

        :param host: An ip to connect too
        :type host: str
        :param port: The port to connect too
        :type port: int
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



