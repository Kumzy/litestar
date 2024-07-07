from litestar.channels import ChannelsPlugin as Channels

async with Channels.start_subscription(["foo", "bar"]) as subscriber:
    # do some stuff here
    await Channels.unsubscribe(subscriber, ["foo"])
