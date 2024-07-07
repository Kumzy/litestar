from litestar.channels import ChannelsPlugin as Channels

subscriber = await Channels.subscribe(["foo", "bar"])
try:
    ...  # do some stuff here
finally:
    await Channels.unsubscribe(subscriber)
