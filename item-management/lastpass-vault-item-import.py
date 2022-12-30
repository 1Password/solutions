#!/usr/bin/env python3

#This script will create vaults and login items from a LastPass export. 

#Shared/Nested folders in 1Password will have separate vaults created. Items not belonging to any shared folder will be created in the user's private vault.



import csv, os
vault_list = []
with open('export.csv', newline='') as csvfile:
    linereader = csv.reader(csvfile, delimiter=',', quotechar='"')
    next(linereader)

    
    for row in linereader:
        url = row[0]
        username = row[1]
        password = row[2]
        notes= row[4]
        title = row[5]        
        vault = row[6]
        
        #omitting Secure Notes
        if url == "http://sn":
            continue
        
        if not vault or vault == "":
            os.system('''op item create --vault="Private" \\
                --tags="%s" \\
                --category=login \\
                --title="%s" \\
                --url="%s" \\
                username="%s" \\
                password="%s" \\
                notes="%s"
                ''' % (vault, title, url, username,password, notes))
            continue
        if vault not in vault_list:
            vault_list.append(vault) 
            #create vault
            os.system('op vault create "%s"'% vault)
            #create item
            os.system('''op item create --vault="%s" \\
                --tags="%s" \\
                --category=login \\
                --title="%s" \\
                --url="%s" \\
                username="%s" \\
                password="%s"
                notes="%s"
                ''' % (vault,vault, title, url, username,password, notes))
            continue
        if vault in vault_list:
            #create item
            os.system('''op item create --vault="%s" \\
                --tags="%s" \\
                --category=login \\
                --title="%s" \\
                --url="%s" \\
                username="%s" \\
                password="%s"
                notes="%s"
                ''' % (vault,vault, title, url, username,password, notes))
            continue
        
        