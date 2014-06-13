from ws4py.client.threadedclient import WebSocketClient
from threading import Thread
import time
import json
import uuid

#
# A simple queue, and the right way to send messages in LivelyClient.  In many
# cases, messages should not be sent until some condition holds.  So this
# simply acts as a gate: checks to see if it's allowed to send messages,
# (readyToSend = True), and if it is sends the message.  Otherwise, it sticks
# it on the queue to send.  When enableSending() is called, sends all queued
# messages and sets readyToSend = True
# protocol: starts out with sending disabled
#     MessageQueue(client): create a new message queue with sending disabled
#     queueToSend(action, data, targetID): send a message to targetID, where the
#                message is the usual Lively2Lively pair (action, data).  Send is
#                immediate if sending is enabled; otherwise, the message is queued
#                until sending is enabled
#     enableSending(): send all queued messages and enable immediage sending for
#                the future
#     disableSending(): turn off immediate send
#     setTargetID(id): set the targetID for all queued and future messages
#

class MessageQueue:
    def __init__(self, socketClient):
        self.readyToSend = False
        self.queuedMessages = []
        self.socketClient = socketClient
    
    def queueToSend(self, action, data, otherID = None):
        if self.readyToSend:
            self.socketClient.send_message(action, data, otherID)
        else:
            self.queuedMessages.append({'action':action, 'data':data, 'id':otherID})
    
    def enableSending(self):
        self.readyToSend = True
        while len(self.queuedMessages) > 0:
            msg = self.queuedMessages.pop()
            self.socketClient.send_message(msg['action'], msg['data'], msg['id'])
    
    def disableSending(self):
        self.readyToSend = False
        
    def setTargetID(self, id):
        for msg in self.queuedMessages: msg['id'] = id

#
# A Lively2Lively client.  This object uses ws4py to present an abstraction of a
# Lively2Lively client, and permits a Python program to interact with a Lively page
# This involves sending a json dictionary {action: <string>, data:<json-object>}
# to a Lively page at url <urlToFind>.
# members: user (Lively userid of the person using this library)
#          urlToFind: URL of the Lively page to connect to
#
# 
        
class LivelyClient(WebSocketClient):
    def __init__(self, user, urlToFind):
        WebSocketClient.__init__(self, 'ws://www.lively-web.org/nodejs/SessionTracker/connect', protocols=['lively-json'])
        self.user = user
        self.sessionID = str(uuid.uuid4())
        self.handlers = {}
        self.otherID = None
        self.sendOnConnectionQueue = MessageQueue(self)
        self.sendToPeerQueue = MessageQueue(self)
        self.livelyPeerURL = urlToFind
        def find_correct_peer(client, data):
            for trackerID in data:
                client_session = data[trackerID]
                if len(client_session.keys()) == 0: continue
                for id in client_session:
                    session_data = client_session[id]
                    if not 'worldURL' in session_data: continue
                    if session_data['worldURL'] == client.livelyPeerURL:
                        client.otherID = id
                        client.sendToPeerQueue.setTargetID(client.otherID)
                        client.sendToPeerQueue.enableSending()
                        print 'Found the peer at ' + id
                        return
            # if we get here, it wasn't found.  Since this might be
            # a timing thing, wait a minute and try again
            client.setMessageHandler('getSessions', find_correct_peer)
            client.sendOnConnection('getSessions', {'options':[]})
        self.setMessageHandler('getSessions', find_correct_peer)
        self.sendOnConnection('getSessions', {'options':[]})
        
        
    # handler should be a function f(lively_client, data)
    # The basic point is that when a message comes in with
    # keyword <action>, this will be called.  the handler
    # function should have a hook for this client, and a hook
    # for the message data.  In general this is a json object
        
    def setMessageHandler(self, action, handler):
        self.handlers[action] = handler
        
    #
    # get the ID of this session
    #
        
    def getSessionID(self):
        return self.sessionID
    
    #
    # get the passed-in user name
    #
    
    def getUser(self):
        return self.user
    
    #
    # get a made-up URL for this world (the L2L Session tracker needs this)
    #
    
    def worldURL(self):
        return 'http://localhost/livelySession/%s/%s' % (self.user, self.sessionID)
        
    #
    # register with the session tracker.  This is called from __init__ and should not
    # ever be called elsewhere
    #
    
    def registerSelf(self):
        livelyData = {'user':self.user, 'id': self.sessionID, 'worldURL': self.worldURL()}
        self.send(json.dumps({'action':'registerClient', 'data':livelyData}))
        
    #
    # Connection closed
    #
                  
    def closed(self, code, reason=None):
        print "Lively Session with tracker closed", code, reason
    
    #
    # Once the session is opened, register ourselves and enable
    # the sending of any messages awaiting connection to the SessionTracker
    #
    
    def opened(self):
        # print 'Connection to Session Tracker Opened!'
        self.registerSelf()
        self.sendOnConnectionQueue.enableSending()
        
    #
    # Receive a message.  Parse it, look for a handler, and if there
    # is one, call it.  Otherwise, call the messageNotUnderstood method
    #
        
    def received_message(self, msg):
        # print "Message Received: " + str(msg)
        msgAsData = json.loads(str(msg))
        action = msgAsData['action']
        if (action in self.handlers):
            self.handlers[action](self, msgAsData['data'])
        else:
            self.messageNotUnderstood(action, msgAsData['data'])
    
    #
    # Got a message we didn't understand.  Just print it for now
    #
    
    def messageNotUnderstood(action, data):
        print("Got a message we didn't understand.  action: %s, data: %s" % (actiomn, str(data)))
    
    #
    # send a mesaage (action, data) to target.  THIS SHOULD ONLY BE CALLED INTERNALLY.
    # To send, use one of the sendOnConnection and sendToPeer methods, which will queue
    # the messages until it's safe to send
    #
            
    def send_message(self, action, data, otherID = None):
        msg = json.dumps({'action':action, 'data': data, 'target':otherID})
        # print "Sending message ", msg
        self.send(msg)
    
    #
    # send to (typically, the SessionTracker) once a connection has been established.
    # parameters action, data,the two components of an L2L message.  External
    # clients should not need to call this.  This is typically only used in the handshake
    # to get the ID of the peer; clients of this class should use sendToPeer exclusively
    # send to the Lively client at URL self.livelyPeerURL
    #
    
    def sendOnConnection(self, action, data):
        self.sendOnConnectionQueue.queueToSend(action, data)
    
    #
    # send a message to the peer at 
        
    def sendToPeer(self, action, data):
        self.sendToPeerQueue.queueToSend(action, data, self.otherID)
        
class LivelyClientRunner(Thread):
    def __init__(self, livelyClient):
        Thread.__init__(self)
        self.livelyClient = livelyClient
    
    def run(self):
        self.livelyClient.connect()
        self.livelyClient.run_forever()
        


#
# A little test program
#


def test_result(client, data):
    print 'It worked! ' + str(data['answer'])
    
#
# The test shows the basic structure of using livelyClient
# 1. Create it with a Lively UserID
# 2. Create a thread to run it
# 3. Initialize a bunch of message handlers to respond to actions
# 4. start the lively thread
# 5. Send some messages, etc, using sendToPeer.  These can be done before 4, too.
#    Since they just get queued then it really doesn't matter.
#


if __name__ == '__main__':
    try:
        livelyClient = LivelyClient('rick', 'http://www.lively-web.org/users/rick/testl2l.html')
        runner = LivelyClientRunner(livelyClient)
        livelyClient.setMessageHandler('users.rick.myClientServiceResult', test_result)
        livelyClient.sendToPeer('users.rick.myClientService', 'hello, world!')
        runner.start()
        time.sleep(60)
        runner.__stop()
        livelyClient.close()
        
    except KeyboardInterrupt:
        runner.__stop()
        livelyClient.close()
        
        
        
        
        
        
        


    