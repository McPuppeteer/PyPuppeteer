from connection import *
import asyncio




class Player:
	async def _callback_handler(self, info):
		# print(info)
		pass
		

	def __init__(self, connection : ClientConnection):
		self.connection = connection
		self.connection.callback_handler = self._callback_handler
	def handle_json(self, packet_type, json):
		assert packet_type == ord('j')
		if json.get("status") == "error":
			raise PuppeteerError("Error: " + json.get("message", ""), etype=strType2error(json.get("type")))
		del json["status"]
		del json["id"]
		return json

	@classmethod
	async def discover(cls, with_name=None):
		async for broadcast, (host, _) in getBroadcasts():
			if with_name is not None and broadcast["player username"] != with_name:
				continue

			connection = ClientConnection(host, broadcast["port"])
			await connection.start()
			return cls(connection)

	async def __aenter__(self):
		return self
	async def __aexit__(self, exc_type, exc, tb):
		await self.connection.__aexit__(exc_type, exc, tb)



	# Informational functions

	async def getClientInfo(self):
		""" Returns a dictionary of a bunch of information about the game client """
		return self.handle_json(*await self.connection.write_packet("client info") )
	async def getInstalledMods(self):
		return self.handle_json(*await self.connection.write_packet("get mod list") )["mods"]



	# World/server function

	async def getServerList(self):
		""" Gets all the multiplayer servers in your server list, along with the "hidden" ones (your direct connect history). """
		return self.handle_json(*await self.connection.write_packet("get server list") )
	async def getWorldList(self):
		""" 
		List ALL the worlds on this minecraft instances .minecraft folder.

		This can be slow on some installs, as some users may have <b>thousands</b> of worlds.
		"""
		return self.handle_json(*await self.connection.write_packet("get worlds") )
	async def joinWorld(self, name : str):
		"""
		Joins a local world. The name <b>needs</b> to be from the 'load name' from getWorldList()
		
		:param name: The name of the world to join, <b>needs</b to match the 'load name' from getWorldList()
		:type name: str
		"""
		return self.handle_json(*await self.connection.write_packet("join world", {"load world": name}) )
	async def joinServer(self, address : str):
		"""
		Joins a multiplayer server

		:param address: Server ip to connect to
		:type address: str
		"""

		return self.handle_json(*await self.connection.write_packet("join server", {"address": address}) )


	async def baritoneGoto(self, x : int, y : int, z : int, force : bool = True):
		return self.handle_json(*await self.connection.write_packet("baritone goto", {
			"x": x,
			"y": y,
			"z": z,
			"no cancel": not force
		}) )



	async def getFreecamState(self) -> bool:
		return (await self.connection.write_packet("is freecam"))["is freecam"]
	async def getFreerotState(self) -> bool:
		return (await self.connection.write_packet("is freerot"))["is freerot"]

	async def setFreecam(self, enabled : bool = True):
		return self.handle_json(*await self.connection.write_packet("set freecam", {"enabled": enabled}) )
	async def setFreerot(self, enabled : bool = True):
		return self.handle_json(*await self.connection.write_packet("set freerot", {"enabled": enabled}) )


	async def toggleFreecam(self):
		return await self.setFreecam(not (await self.getFreecamState()))
	async def toggleFreerot(self):
		return await self.setFreerot(not (await self.getFreerotState()))

	async def rotate(self, pitch : float, yaw : float, speed : float = 3, method : RoMethod = RoMethod.SINE_IN_OUT):
		return self.handle_json(*await self.connection.write_packet("algorithmic rotation", {
			"pitch": pitch, 
			"yaw": yaw,	
			"degrees per tick": speed,
			"interpolation": method.value
		}) )
	async def instantRotate(self, pitch : float, yaw : float):
		return self.handle_json(*await self.connection.write_packet("instantaneous rotation", {
			"pitch": pitch,
			"yaw": yaw
		}) )
import time

async def main():
	async with await Player.discover() as p:
		# await p.setFreecam(True)
		print("x")
		t = time.time()
		print(await p.instantRotate(0, 0))
		print(time.time() - t)
		

		# print(await p.baritoneGoto(1, 1, 1, True))

		# await asyncio.sleep(5)
		# print((await p.getClientInfo())["uuid"])
		# print((await p.getClientInfo())["uuid"])
		# print((await p.getClientInfo())["uuid"])
		# print((await p.getClientInfo()))
		
		
		# # tweakeroo


if __name__ == "__main__":

	asyncio.run(main())

