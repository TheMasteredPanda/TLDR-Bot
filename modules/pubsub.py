import time
import asyncio


class Publisher(object):

    def __init__(self, collection, event):
        self.collection = collection
        self.event = event

    def push(self, data):
        data['event'] = self.event
        self.collection.insert(data)


class Subscriber(object):

    def __init__(self, collection, event, callback, matching=None):
        self.collection = collection
        self.event = event
        self.callback = callback
        self.check_interval = 1  # 1 second

        self.matching = matching
        self.matching['event'] = self.event

        self.start_time = time.time()

    async def wait_for(self):
        while True:
            record = self.collection.find_one(self.matching)
            if not record:
                await asyncio.sleep(self.check_interval)
                if time.time() - self.start_time >= 300: # Kills timer after 5 mins
                    return False
            else:
                await self.callback(record)
                self.collection.delete_one(self.matching)
                return False

    def listen(self):
        asyncio.create_task(self.wait_for())
