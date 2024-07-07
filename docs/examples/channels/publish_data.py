from litestar.channels import ChannelsPlugin as Channels

Channels.publish({"message": "Hello"}, "general")
