from connection import *
import asyncio




class Player:
	async def _callback_handler(self):
		pass
	

	def __init__(self, connection : ClientConnection):
		self.connection = connection
		self.connection.callback_handler = self._callback_handler
	def clean_json(self, packet_type, json):
		assert packet_type == ord('j')
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
		return self.clean_json(*await self.connection.write_packet("client info") )
	async def getInstalledMods(self):
		return self.clean_json(*await self.connection.write_packet("get mod list") )["mods"]



	# World/server function

	async def getServerList(self):
		""" Gets all the multiplayer servers in your server list, along with the "hidden" ones (your direct connect history). """
		return self.clean_json(*await self.connection.write_packet("get server list") )
	async def getWorldList(self):
		""" 
		List ALL the worlds on this minecraft instances .minecraft folder.

		This can be slow on some installs, as some users may have <b>thousands</b> of worlds.
		"""
		return self.clean_json(*await self.connection.write_packet("get worlds") )
	async def joinWorld(self, name : str):
		"""
		Joins a local world. The name <b>needs</b> to be from the 'load name' from getWorldList()
		
		:param name: The name of the world to join, <b>needs</b to match the 'load name' from getWorldList()
		:type name: str
		"""
		return self.clean_json(*await self.connection.write_packet("join world", {"load world": name}) )
	async def joinServer(self, address : str):
		"""
		Joins a multiplayer server
		"""
		return self.clean_json(*await self.connection.write_packet("join server", {"address": address}) )



async def main():
	async with await Player.discover() as p:
		print(await p.connection.write_packet("get config", {"file name" : "mc-puppeteer.json"}))
		# tweakeroo


if __name__ == "__main__":

	asyncio.run(main())

