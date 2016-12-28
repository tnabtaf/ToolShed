#!/usr/local/bin/python3
# -*- coding: utf-8 -*-
##
# Parsing emails from the tool shed in a Gmail account
# This generates markdown listing any tools that were added to the ToolShed or
# updated after the specified date.
#
# Markdown will look like
#
# * From [username in toolshed][(URL of user home in ToolShed)
#   * [name of tool](URL of tool in ToolShed): description from one or more places.
#   * [name of tool](URL of 2nd tool in ToolShed): description from one or more places.
#

import argparse
import getpass                            #
import imaplib                            # Email protocol
import urllib.parse
import os.path
import json                               # tool shed respoonses
import urllib.request
import re

HOST = "imap.gmail.com"
# TOOLSHED_SENDER = "galaxy-no-reply@montana.galaxyproject.org"  # True until 2015/04/22
# TOOLSHED_SENDER = "galaxy-no-reply@radegast.galaxyproject.org"   # Sender from 2015/04/22 to 2016/07/23
TOOLSHED_SENDER = "galaxy-no-reply@toolshed.g2.bx.psu.edu"   # Sender from 2016/07/27 on

HEADER_PARTS = "(BODY.PEEK[HEADER.FIELDS (From Subject)])"
BODY_PARTS = "(BODY.PEEK[TEXT])"

# indexes into tuple for each part
FROM    = 0
SUBJECT = 1

LINK_LINE = 1
REPO_LINE = 2
REVISION_LINE = 3
DESCR_START_LINE = 5

TOOLSHED_API_ROOT_URL = "https://toolshed.g2.bx.psu.edu/api/"


def polish(text):
    """
    Polish text before printing it.

    1. Strip leading and trailing whitespace.
    2. Replace embedded newlines with spaces
    3. Add a trailing period to text, if it does not already have one.
    """
    text = text.strip()
    if len(text) > 0 and text[-1:] not in [".", r"\n", " "]:
        text += "."
    text = text.replace("\n", "  ")
    return(text)



        
class ToolShedRepo:
    """
    Describes a Tool shed repo.
    """
    
    def __init__(self, headerTxt, bodyTxt):
        """
        Takes result of two IMAP fetches to create a ToolShedRepo object.  It also uses 
        this information to access the ToolShed API to extract out the description and 
        long description of each repo.
        """
        self.parseEmail(headerTxt, bodyTxt)
        self.getToolShedInfo()
        return(None)

    
    def parseEmail(self, headerTxt, bodyTxt):
        """
        Typical header:
          [('3 (UID 3 BODY[HEADER.FIELDS (From Subject)] {95}',
            'From: galaxy-no-reply@montana.bx.psu.edu\r\n
             Subject: Galaxy tool shed repository update alert\r\n\r\n'
           ),
           ')']
        Typical Body:
          [('3 (UID 3 BODY[TEXT] {678}',
            '\r\n
            Sharable link:         https://toolshed.g2.bx.psu.edu/view/kaymccoy/calculate_fitness\r\n
            Repository name:       calculate_fitness\r\n
            Revision:              0:babd6d75a0b0\r\n
            Change description:\r\n
            Uploaded\r\n
            \r\n
            Uploaded by:           kaymccoy\r\n
            Date content uploaded: 2016-11-06\r\n'

            OR
            '\r\n
            Sharable link:         https://toolshed.g2.bx.psu.edu/view/devteam/ncbi_blast_plus\r\n
            Repository name:       ncbi_blast_plus\r\n
            Revision:              20:3034ce97dd33\r\n
            Change description:\r\n
            Uploaded v0.1.08, can search multiple local databases, fixes a pipe problem in blastdbcmd, and minor internal changes.\r\n
            \r\n
            Changed by:     peterjc\r\n
            Date of change: 2016-11-07\r\n'

            both ending with
            '\r\n
            \r\n
            \r\n
            -----------------------------------------------------------------------------\r\n
            This change alert was sent from the Galaxy tool shed hosted on the server\r\n
            "toolshed.g2.bx.psu.edu"\r\n
            -----------------------------------------------------------------------------\r\n
            You received this alert because you registered to receive email whenever\r\n
            changes were made to the repository named "ncbi_blast_plus".\r\n
            -----------------------------------------------------------------------------\r\n'
           ),
           ')']
        """
        global args
        # Parse header info
        _headers = headerTxt[0][1].decode("utf-8").split("\r\n")
        self.sender = _headers[FROM][6:]
        self.subject = _headers[SUBJECT][9:]
        if self.sender != TOOLSHED_SENDER:
            return None                   # need to raise an error.

        # split body into an array of lines of text
        self.body = bodyTxt[0][1].decode("utf-8").split("\r\n")

        # extract repo link, which also contains author url
        self.url = self.body[LINK_LINE].split()[2]
        _urlParts = urllib.parse.urlparse(self.url)
        _authorPath, self.name = os.path.split(_urlParts.path)
        self.authorUrl = _urlParts.scheme + "://" + _urlParts.netloc + _authorPath     
        self.author = self.authorUrl.split("/")[-1]

        # Extract revision ID
        self.revision = self.body[REVISION_LINE].split(":")[2]

        # Extract commit message
        self.commit = ""
        line = DESCR_START_LINE
        while self.body[line].split(":")[0] not in ("Uploaded by", "Changed by"):
            lineParts = self.body[line].split(" ")

            if lineParts[0] == "Uploaded": # the default value
                if len(lineParts) > 1:
                    self.commit += " ".join(lineParts[1:])
            elif (args.args.stripplanemocommittext and
                      lineParts[0] == "planemo" and lineParts[1] == "upload"):
                pass
            else:
                self.commit += self.body[line]
            # add a period.
            self.commit = polish(self.commit)
            line += 1
        return(None)

    def getToolShedInfo(self):
        """
        Extract info about this repo from the toolshed.
        """
        # Get the synopisis and long description of the repo using the ToolShed API.
        # https://toolshed.g2.bx.psu.edu/api/repositories/get_repository_revision_install_info?name=mirplant2&owner=big-tiandm&changeset_revision=2cb6add23dfe
        _tsApiUrl = (TOOLSHED_API_ROOT_URL + "repositories/get_repository_revision_install_info?" +
                    "name=" + self.name + "&owner=" + self.author + "&changeset_revision=" + self.revision)
        response = urllib.request.urlopen(_tsApiUrl).read().decode("utf-8")
        # take out embedded \r's in the text.
        response = response.replace(r"\r", "")
        _tsData = json.loads(response)
        
        # passe just means we aren't interested.
        self.passe = _tsData[0]["deleted"] or _tsData[0]["deprecated"] or _tsData[1]["malicious"]
        self.synopsis = ""
        self.description = ""
        self.type = "Unknown"
        if "description" in _tsData[0]:
            self.synopsis = polish(_tsData[0]["description"])
        if "long_description" in _tsData[0]:
            self.description = polish(_tsData[0]["long_description"])
        if "type" in _tsData[0]:
            self.type = _tsData[0]["type"]
        return(None)
        

    def isUpdate(self):
        """
        Toolshed emails are either new repos or updates.  Can tell by looking at
        the subject line
        """
        return (self.subject.split()[3] == "update")

    def isNew(self):
        """
        Toolshed emails are either new repos or updates.  Can tell by looking at
        the subject line
        """
        return (self.subject.split()[3] == "alert")

    def isPasse(self):
        """
        Answers the age old question: is this repo no longer stylish?
        """
        return self.passe

class Arrgghhss(object):
    """
    Process and provide access to command line arguments.
    """

    def __init__(self):
        argParser = argparse.ArgumentParser(
            description="Generate markdown to describe ToolShed updates within a given period.")
        argParser.add_argument(
            "-e", "--email", required=True,
            help="GMail account to pull ToolShed update notices from")
        argParser.add_argument(
            "--toemail", required=False,
            help="Optional. Use if the email account is different than the email address notifications are sent to.")
        argParser.add_argument(
            "--mailbox", required=True,
            help="Mailbox containing ToolShed update emails. Example 'Tool Shed' ")
        argParser.add_argument(
            "--sentsince", required=True,
            help=("Only look at email sent after this date." +
                    " Format: DD-Mon-YYYY.  Example: 01-Dec-2014."))
        argParser.add_argument(
            "--sentbefore", required=False,
            help=("Optional. Only look at email sent before this date." +
                    " Format: DD-Mon-YYYY.  Example: 01-Jan-2015."))
        argParser.add_argument(
            "--stripplanemocommittext", required=False, default=False, action='store_true', 
            help=("Optional. Remove commit text generated by planemo commits."))
        self.args = argParser.parse_args()

        return(None)

# Main
        
newToolRepos = {}
updates = {}
passe = []

args = Arrgghhss()                        # Command line args

# Establish Email connection, get emails.

email = imaplib.IMAP4_SSL(HOST)
email.login(args.args.email, getpass.getpass())
email.select('"' + args.args.mailbox + '"', True)

emailSearchArgs = []
emailSearchArgs.append('SENTSINCE ' + args.args.sentsince)
if args.args.sentbefore:
    emailSearchArgs.append('SENTBEFORE ' + args.args.sentbefore)
emailSearchArgs.append('HEADER From "' + TOOLSHED_SENDER + '"')
if args.args.toemail:
    emailSearchArgs.append('To "' + args.args.toemail + '"')

emailSearch = "(" + " ".join(emailSearchArgs) + ")"

typ, msgNums = email.uid('search', None, emailSearch)


# Process the emails.

for msgNum in msgNums[0].split():
    typ, header = email.uid("fetch", msgNum, HEADER_PARTS)    
    typ, body = email.uid("fetch", msgNum, BODY_PARTS)
    
    repo = ToolShedRepo(header,body)
    # Save repos by type, author and then name.
    if repo.isPasse():
        passe.append(repo)
    elif repo.isNew():
        if repo.type not in newToolRepos:
            newToolRepos[repo.type] = {}
        if repo.author not in newToolRepos[repo.type]:
            newToolRepos[repo.type][repo.author] = {}
        # duplicate emails are common for new repos; avoid them
        if repo.name not in newToolRepos[repo.type][repo.author]:
            newToolRepos[repo.type][repo.author][repo.name] = repo
    elif repo.isUpdate():
        if repo.type not in updates:
            updates[repo.type] = {}
        if repo.author not in updates[repo.type]:
            updates[repo.type][repo.author] = {}
        if repo.name not in updates[repo.type][repo.author]:
            updates[repo.type][repo.author][repo.name] = []
        updates[repo.type][repo.author][repo.name].append(repo)
    else:
        print("Not a tool shed repo:")
        print(header)

# Generate the makrdown report.
        
print("### New Tools")

for repoType, authors in newToolRepos.items():
    print("\n#### %s" % (repoType))
    for authorRepos in authors.values(): 
        first = True
        for repo in authorRepos.values():
            if first:
                print ("* *From [%s](%s):*" % (repo.author, repo.authorUrl))            
                first = False
            print ("   * [%s](%s): %s %s %s" % (repo.name, repo.url, repo.commit, repo.synopsis, repo.description))

print("\n\n### Select Updates ")
for repoType, authors in updates.items():
    print("\n#### %s" % (repoType))
    for authorsRepos in authors.values():
        first = True
        for repos in authorsRepos.values():
            for update in repos:
                if first:
                    print ("* *From [%s](%s):*" % (update.author, update.authorUrl))
                    first = False
                print ("   * [%s](%s): %s" % (update.name, update.url, update.commit)) 

print("\n\n### Passe")
for repo in passe:
    print ("   * [%s](%s): %s" % (repo.name, repo.url, repo.commit)) 
    
email.close()                             # close mailbox
email.logout()                            # closs connection
