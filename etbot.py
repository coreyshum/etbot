import re
import ast
import sys
import time
import datetime
import shelve
from pprint import pprint

import httplib
import httplib2
import ssl

from trolly.client import Client
from trolly.board import Board
from trolly.list import List
from trolly.card import Card
from trolly import ResourceUnavailable 

import keys

originDB= shelve.open('etbot-card-origins', writeback=True)


def markProjectInDesc(desc, project=None):
    delims= ('project:__', '__')

    # remove projects marked earlier
    for loc in [(m.start(),m.end()) for m in re.finditer(delims[0]+'.*?'+delims[1], desc)]:
        desc= desc[:loc[0]]+desc[loc[1]:]

    if project and (desc != 'General'):
        # add new project mark
        desc= delims[0]+' '+str(project)+' '+delims[1]+'\n'+desc

    return desc



def manageActive():
    changesMade= False
    
    client= Client(keys.api_key, keys.user_auth_token)

    # for each card in "Project Backlog" board:
    #   if card is labeled "Active" (green):
    #     record its original list & pos
    #     mark the description with its origin project list name (if not "General")
    #     move it to "This Week" list in "Active" board

    # for each card in "Active" board:
    #   if card is in "Finished" list:
    #     remove label "Active" (green)
    #   else:
    #     if card is not labeled "Active" (green):
    #       move it back to its original list & pos (in "Project Backlog" board)
    #       remove project mark in description

    # for each card in "Finished" list that has been archived:
    #   move such cards to lists in the "Closed" board that correspond to their
    #   origin project list in "Project Backlog" board, creating if needed,
    #   then un-archive the card in its new position

    # ----------------------------------------------------------------------------

    # for each card in "Project Backlog" board:
    backlogBoard= Board(client, keys.boardIds['backlog'])
    backlogCards= backlogBoard.getCardsJson(backlogBoard.base_uri)

    for card in backlogCards:

        # if card is labeled "Active" (green):
        labels= [i['color'] for i in card['labels']]
        if 'green' in labels:

            cardHandle= Card(client, card['id'])

            originDB[str(card['id'])]= (card['idList'], card['pos'])

            # mark its description with the project list name
            projectName= List(client, card['idList']).getListInformation()['name']
            desc= markProjectInDesc(card['desc'], projectName)
            cardHandle.setDesc(desc)
            
            # move it to "This Week" list in "Active" board
            cardHandle.moveTo(keys.boardIds['active'], keys.listIds['this week'])

            # reset labels
            for l in labels:
                cardHandle.addLabel(l)

            changesMade= True

    

    # for each card in "Active" board:
    activeBoard= Board(client, keys.boardIds['active'])
    activeCards= activeBoard.getCardsJson(activeBoard.base_uri)

    for card in activeCards:

        labels= [i['color'] for i in card['labels']]

        # if card is in "Finished" list or "Overview" list:
        if ((card['idList'] == keys.listIds['finished'])
            or (card['idList'] == keys.listIds['overview'])):
            cardHandle= Card(client, card['id'])

            # remove all labels
            for l in labels: 
                cardHandle.removeLabel(l)
                changesMade= True
                
        else:
         # if card is not labeled "Active" (green):
            if 'green' not in labels:

                # move it back to its original list & pos (in "Project Backlog" board)
                cardHandle= Card(client, card['id'])

                # remove project list name from its description
                desc= markProjectInDesc(card['desc'], None)
                cardHandle.setDesc(desc)

                # fallback origin
                try:
                    origin= originDB[str(card['id'])]
                    cardHandle.moveTo(keys.boardIds['backlog'], origin[0], origin[1])
                except (ResourceUnavailable, KeyError):
                    fallbackOrigin= (keys.listIds['general'], 'bottom')
                    cardHandle.moveTo(keys.boardIds['backlog'], fallbackOrigin[0], fallbackOrigin[1])

                # reset labels
                for l in labels:
                    cardHandle.addLabel(l)

                changesMade= True


    # for each card in Active / Finished that has been archived
    activeFinishedCards= List(client, keys.listIds['finished'])
    activeFinishedCardsInfo= activeFinishedCards.fetchJson(activeFinishedCards.base_uri+'/cards',
                                                           query_params={'filter':'closed'})

    closedBoard= Board(client, keys.boardIds['closed'])

    for card in activeFinishedCardsInfo:
        cardHandle= Card(client, card['id'])
        changesMade= True

        # find origin destination
        try:
            originListId, pos= originDB[str(card['id'])]
            destListName= List(client, originListId).getListInformation()['name']

            destListId= None
            
            # get id in closed board for list with that name, or else make one
            for l in closedBoard.getListsJson(closedBoard.base_uri):
                if l['name'] == destListName:
                    #print '[%s] [%s] %s' %(l['name'], destListName, l['name'] == destListName)
                    destListId= (l['id'], 'top')

            if not destListId: 
                newList= closedBoard.addList({'name': destListName, 'pos': 'bottom'})
                #print 'CREATED:', newList.name, newList.id
                destListId= (newList.id, 'top')
            
        except (ResourceUnavailable, KeyError):
            # fallback dest
            destListId= (keys.listIds['closed general'], 'top')
            destListName= 'General'

        # remove project list name from its description
        desc= markProjectInDesc(card['desc'], None)
        cardHandle.setDesc(desc)

        #print card['name'], 'to:', destListName, destListId[0]

        try:
            # move card to destination list on closed board and un-archive
            cardHandle.moveTo(keys.boardIds['closed'], destListId[0], destListId[1])
            cardHandle.setClosed('false')
        except ResourceUnavailable:
            # sometimes new lists aren't ready quite yet.  Let's try next time
            pass



    originDB.sync()

    return changesMade



if __name__ == '__main__':

    # when changes have been needed, check back in 1 sec.
    # if changes aren't needed, increase the delay by a small factor,
    #   to a maximum delay based on the time of day.
    # for example, if a change is needed at noon, it will take at most
    #   60 sec before the bot works.  It will then check the next 1 sec
    #   for changes, and then if none, it will continue to check more & more
    #   slowly until it reaches the maximum delay for noon of 120 sec again.
    
    delay= 1.0
    
    maxDelays= [ 900, 900, 900, 900,
                 900, 240, 120, 60,
                 60, 60, 60, 60,
                 60, 60, 60, 60,
                 60, 60, 60, 60,
                 120, 120, 240, 900 ]
    
    while True:

        now= datetime.datetime.now()

        try:
            success= manageActive()
        except (httplib2.ServerNotFoundError,
                httplib.BadStatusLine,
                ssl.SSLError,
                ResourceUnavailable):
            sys.stderr.write('ERROR: server problem at %d:%02d.\n' % (now.hour, now.minute))
            success= False
        
        if success:
            sys.stderr.write('etbot activated at %d:%02d.\n' % (now.hour, now.minute))
            delay= 1.0
        else:
            delay*= 1.2

        maxDelay= maxDelays[datetime.datetime.now().hour]
        #print '    (delay is %0.1f)' % min(delay, maxDelay)
        time.sleep(min(delay, maxDelay))

    
    #import code
    #code.interact(local=globals())
