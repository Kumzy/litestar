from litestar.channels import ChannelsPlugin as channels

async with channels.start_subscription(["foo", "bar"]) as subscriber:
    ...  # do some stuff here
