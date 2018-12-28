# py-ts3bot
py-ts3bot is a simple TeamSpeak3 ServerQuery Bot written in Python3.  
Its current features consists of activity tracking of users and servergroup assignments based on that and the automaitc creation and deletion of channels as they are needed.  
In its current status it is tailored for the specific TeamSpeak Server it is used on but should be usable with other ones aswell. But for other usecases it still lacks better customizability and better error handling. Nevertheless someone might still find it useful for their own server or to create their own bot.


## Config  
An example configuration can be found in the repository for the case that you actually want to deploy the bot yourself. The basic stuff should be self-explanatory.

### Ranking System
`default_group` specifies the default group a user is assigned on you server  
`channel_blacklist` specifies a list of cids for which the bot should not track activity of users  
`rankings` the key specifies the servergroup to watch, `minutes` specifies the minutes of activity a user has to reach to rank up and `to` specifies the servergroup to be assigned on rank up

### Channel Creation
`watchlist` the key specifies the parent channel to track and under which channels are created, `prefix` specifies the prefix of the created channels, that will be numbered, `max_clients` specifies the maximum numer of clients in the created channels, `icon_id` its icon and `join_power`the needed join power in order to join


## Dependencies
`ts3==2.0.0b2`