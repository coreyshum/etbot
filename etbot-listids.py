import re
import ast
import sys
from pprint import pprint

from trolly.client import Client
from trolly.board import Board
from trolly.list import List

import keys

if __name__ == '__main__':
    client= Client(keys.api_key, keys.user_auth_token)

    board= Board(client, sys.argv[1])
    for l in board.getLists():
        print l.name, l.id
        
