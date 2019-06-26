import ts3
import sqlite3
import os
import sys
import time
import logging
import json
from logging.handlers import RotatingFileHandler

last_time = int(time.time())


def main():
    with ts3.query.TS3ServerConnection(URI) as ts3conn:
        # connect to server instance, update name and go to specific channel
        ts3conn.exec_("use", sid=SID)
        ts3conn.exec_("clientupdate", client_nickname=CLIENT_NAME)
        myclid = ts3conn.exec_("whoami")[0]["client_id"]
        ts3conn.exec_("clientmove", clid=myclid, cid=JOIN_CHANNEL_ID)

        # setup database if it does not exist
        if not os.path.isfile(DATABASE):
            logger.info("No database found, creating new one")
            setup_db()
        dbconn = sqlite3.connect(DATABASE)

        check_channel(ts3conn)
        while True:
            try:
                monitor(ts3conn, dbconn)
            except KeyboardInterrupt:
                dbconn.close()
                logger.info("Ctrl-c pressed, shutting down")
                sys.exit(0)
            except Exception as e:
                if ts3conn.is_connected():
                    logger.exception(str(e))
                    logger.exception("Exception occurred but connection is still open")
                    continue
                else:
                    raise


# Function handling the events and initiating activity logs
def monitor(ts3conn, dbconn):
    # register for all events in server wide chat
    ts3conn.exec_("servernotifyregister", event="channel", id=0)
    ts3conn.exec_("servernotifyregister", event="textprivate")
    ts3conn.send_keepalive()
    try:
        event = ts3conn.wait_for_event(timeout=10)[0]
    except ts3.query.TS3TimeoutError:
        update_ranking(ts3conn, dbconn)
    else:
        # event containing such an reasonid should mean client movement and therefore we check the channels
        if "reasonid" in event.keys() and int(event["reasonid"]) < 10:
            check_channel(ts3conn)
        # received private message
        if "targetmode" in event.keys() and "invokeruid" in event.keys() and int(event["targetmode"]) == 1 and event["invokeruid"] in MODERATOR_UIDS:
            if event["msg"] == "!stats":
                logger.debug(event["invokername"] + " asked for stats")
                send_stats(ts3conn, dbconn, event["invokerid"])
            elif event["msg"].startswith("!search_uid"):
                arguments = event["msg"].split(" ")
                if len(arguments) != 2:
                    ts3conn.exec_("sendtextmessage", targetmode="1", target=event["invokerid"], msg="Invalid arguments")
                    return
                logger.debug(event["invokername"] + " issued search for " + arguments[1])
                search_uid(ts3conn, dbconn, arguments[1], event["invokerid"])
            elif event["msg"].startswith("!search"):
                arguments = event["msg"].split(" ")
                if len(arguments) < 2:
                    ts3conn.exec_("sendtextmessage", targetmode="1", target=event["invokerid"], msg="Invalid arguments")
                    return
                username = " ".join(str(x) for x in arguments[1:])
                logger.debug(event["invokername"] + " issued search for " + username)
                search_user(ts3conn, dbconn, username, event["invokerid"])


# Search for users in database that start with username
# noinspection SqlNoDataSourceInspection,SqlDialectInspection
def search_user(ts3conn, dbconn, username, clid):
    cursor = dbconn.cursor()
    cursor.execute("SELECT uid, name, first_name, time FROM users WHERE LOWER(name) LIKE LOWER(?)", (username + "%", ))
    result = cursor.fetchall()
    if len(result) == 0:
        ts3conn.exec_("sendtextmessage", targetmode="1", target=clid, msg="No user found")
        return

    msg = "\n"
    for row in result:
        msg += row[0] + "\t" + row[1] + " [I]first seen as[/I]  " + row[2] + "\n" + seconds_to_days(row[3]) + "\n"
    ts3conn.exec_("sendtextmessage", targetmode="1", target=clid, msg=msg)


# Search for user in database with specified unique ID
# noinspection SqlNoDataSourceInspection,SqlDialectInspection
def search_uid(ts3conn, dbconn, uid, clid):
    cursor = dbconn.cursor()
    cursor.execute("SELECT uid, name, first_name, time FROM users WHERE uid = ?", (uid,))
    row = cursor.fetchone()
    if row is None:
        ts3conn.exec_("sendtextmessage", targetmode="1", target=clid, msg="No user found")
        return

    ts3conn.exec_("sendtextmessage", targetmode="1", target=clid, msg="\n" + row[0] + "\t" + row[1]
                                                                      + " [I]first seen as[/I]  " + row[2] + "\n"
                                                                      + seconds_to_days(row[3]) + "\n")



# Fetches top 10 active users from the database and sends them to the requester
# noinspection SqlNoDataSourceInspection,SqlDialectInspection
def send_stats(ts3conn, dbconn, clid):
    cursor = dbconn.cursor()
    msg = "\n"
    for row in cursor.execute("SELECT name, first_name, time FROM users ORDER BY time DESC LIMIT 10"):
        msg += row[0] + " [I]first seen as[/I]  " + row[1] + "\n" + seconds_to_days(row[2]) + "\n"
    ts3conn.exec_("sendtextmessage", targetmode="1", target=clid, msg=msg)
    cursor.execute("SELECT COUNT(*), SUM(time) FROM users")
    row = cursor.fetchone()
    msg = "Database contains " + str(row[0]) + " users with a total activity of " + seconds_to_days(row[1])
    ts3conn.exec_("sendtextmessage", targetmode="1", target=clid, msg=msg)


# Function handling the creation and deletion of channels
def check_channel(ts3conn):
    logger.debug("Checking channels")
    for pid in WATCHLIST:
        data = WATCHLIST[pid]
        # try to fetch channels belonging to a group on the watchlist
        try:
            channels = ts3conn.query("channelfind", pattern=data["prefix"]).all()
            cids = [channel["cid"] for channel in channels]
        except (ts3.query.TS3QueryError, KeyError):
            logger.exception("Error in response")
            continue
        if pid in cids:
            cids.remove(pid)

        empty_count = 0
        max_empty_cid = '0'
        max_empty_num = 0
        nums = []
        num_to_cid = {}
        for cid in cids:
            info = ts3conn.exec_("channelinfo", cid=cid)
            # if the parent of the found channel is not the channel on the watchlist skip it
            if info[0]["pid"] != pid:
                continue
            # get channel number
            num = int(info[0]["channel_name"].split(" ")[-1])
            # check if emoty
            if int(info[0]["seconds_empty"]) >= 0:
                empty_count += 1
                if num > max_empty_num:
                    max_empty_cid = cid
            nums.append(num)
            num_to_cid[num] = cid

        # more than one channel empty -> we can delete all empty ones except for one
        if empty_count > 1:
            ts3conn.exec_("channeldelete", cid=max_empty_cid)
            logger.debug("Deleted channel: " + max_empty_cid)
        # all channels are full so we create a new one
        elif empty_count == 0:
            # there exists no channel at all so it is channel 1 and it is ordered first
            if len(nums) == 0:
                free_num = 1
                orderid = "0"
            # determine minimal free number
            else:
                nums.sort()
                free_num = nums[-1]+1
                orderid = num_to_cid[nums[-1]]
                for i in range(1, len(nums)):
                    if nums[i] != nums[i-1] + 1 and nums[i-1]+1 < free_num:
                        free_num = nums[i-1]+1
                        orderid = num_to_cid[nums[i-1]]

            logger.debug("Trying to create channel: " + data["prefix"] + " " + str(free_num))
            ret = ts3conn.exec_("channelcreate", channel_name=data["prefix"] + " " + str(free_num),
                                channel_flag_permanent="1", cpid=pid, channel_order=orderid, channel_codec="4",
                                channel_flag_maxclients_unlimited="0")
            ts3conn.exec_("channeledit", cid=ret[0]["cid"], channel_maxclients=data["max_clients"],
                          channel_codec_quality="10")
            ts3conn.exec_("channeladdperm", cid=ret[0]["cid"], permsid="i_icon_id", permvalue=data["icon_id"])
            ts3conn.exec_("channeladdperm", cid=ret[0]["cid"], permsid="i_channel_needed_modify_power", permvalue="75")
            ts3conn.exec_("channeladdperm", cid=ret[0]["cid"], permsid="i_channel_needed_join_power",
                          permvalue=data["join_power"])
            ts3conn.exec_("channeladdperm", cid=ret[0]["cid"], permsid="i_ft_needed_file_upload_power", permvalue="100")
            ts3conn.exec_("channeladdperm", cid=ret[0]["cid"], permsid="i_ft_needed_file_download_power",
                          permvalue="100")
            ts3conn.exec_("channeladdperm", cid=ret[0]["cid"], permsid="i_ft_needed_file_rename_power", permvalue="100")
            ts3conn.exec_("channeladdperm", cid=ret[0]["cid"], permsid="i_ft_needed_file_browse_power",
                          permvalue="100")
            ts3conn.exec_("channeladdperm", cid=ret[0]["cid"], permsid="i_ft_needed_directory_create_power",
                          permvalue="100")


# Checks all user for their active time, updates the database and if necessary assigns new ranks
# noinspection SqlNoDataSourceInspection,SqlDialectInspection
def update_ranking(ts3conn, dbconn):
    global last_time
    logger.debug("Updating ranks")
    cursor = dbconn.cursor()
    clientlist = ts3conn.exec_("clientlist")
    current_time = int(time.time())
    time_passed = current_time - last_time
    for client in clientlist:
        try:
            info = ts3conn.exec_("clientinfo", clid=client["clid"])[0]
        except ts3.query.TS3QueryError:
            continue

        if int(info["client_idle_time"]) // 1000 < 180 and info["cid"] not in CHANNEL_BLACKLIST:
            cursor.execute("INSERT OR IGNORE INTO users (uid, name, first_name, time) VALUES (?,?,?,0)",
                           (info["client_unique_identifier"], info["client_nickname"], info["client_nickname"]))
            cursor.execute("UPDATE users SET time=time+?, name=? WHERE uid=?",
                           (time_passed, info["client_nickname"], info["client_unique_identifier"]))

            for sg in info["client_servergroups"].split(","):
                if sg in RANKINGS:
                    cursor.execute("SELECT time FROM users WHERE uid=?", (info["client_unique_identifier"],))
                    activity = cursor.fetchone()
                    if activity[0] // 60 >= RANKINGS[sg]["minutes"]:
                        ts3conn.exec_("servergroupaddclient", sgid=RANKINGS[sg]["to"], cldbid=info["client_database_id"])
                        if sg != DEFAULT_GROUP:
                            ts3conn.exec_("servergroupdelclient", sgid=sg, cldbid=info["client_database_id"])
                            logger.debug(client["client_nickname"] + " ranked up to " + RANKINGS[sg]["to"])
                        msg = "[B][COLOR=#ff0000]Herzlichen Glückwunsch zum Rank Up[/COLOR][/B]"
                        ts3conn.exec_("clientpoke", clid=client["clid"], msg=msg)

    dbconn.commit()
    last_time = current_time


# Initial creation of the database scheme
# noinspection SqlNoDataSourceInspection,SqlDialectInspection
def setup_db():
    dbconn = sqlite3.connect(DATABASE)
    c = dbconn.cursor()
    c.execute("CREATE TABLE users (uid text primary key, name text, first_name text, time integer)")
    dbconn.commit()
    dbconn.close()


# Formats seconds to a string in format D:H:M:S
def seconds_to_days(seconds):
    days = seconds // 86400
    seconds = seconds % 86400
    hours = seconds // 3600
    seconds = seconds % 3600
    minutes = seconds // 60
    seconds = seconds % 60
    return str(days) + "D : " + str(hours) + "H : " + str(minutes) + "M : " + str(seconds) + "S"


if __name__ == "__main__":
    with open('config.json') as config_file:
        config = json.load(config_file)

    try:
        DATABASE = config["database"]
        URI = config["uri"]
        SID = config["sid"]
        CLIENT_NAME = config["client_name"]
        JOIN_CHANNEL_ID = config["join_channel_id"]
        MODERATOR_UIDS = set(config["moderator_uids"])

        DEFAULT_GROUP = config["ranking"]["default_group"]
        RANKINGS = config["ranking"]["rankings"]
        CHANNEL_BLACKLIST = set(config["ranking"]["channel_blacklist"])

        WATCHLIST = config["channels"]["watchlist"]

        if config["log_level"] == "CRITICAL":
            LOG_LEVEL = logging.CRITICAL
        elif config["log_level"] == "ERROR":
            LOG_LEVEL = logging.ERROR
        elif config["log_level"] == "WARNING":
            LOG_LEVEL = logging.WARNING
        elif config["log_level"] == "INFO":
            LOG_LEVEL = logging.INFO
        elif config["log_level"] == "DEBUG":
            LOG_LEVEL = logging.DEBUG
        else:
            LOG_LEVEL = logging.NOTSET
    except:
        print("Error parsing config")
        raise

    log_formatter = logging.Formatter("%(asctime)s - %(funcName)s - %(levelname)s - %(message)s")
    log_handler = RotatingFileHandler("ts3bot.log", mode='a', maxBytes=5 * 1024 * 1024, backupCount=2)
    log_handler.setFormatter(log_formatter)
    log_handler.setLevel(LOG_LEVEL)
    # noinspection PyRedeclaration
    logger = logging.getLogger("root")
    logger.setLevel(LOG_LEVEL)
    logger.addHandler(log_handler)

    while True:
        try:
            main()
        except Exception:
            logger.exception("Exception occurred and connection is closed")
            logger.info("Trying to restart in 30s")
            time.sleep(30)
