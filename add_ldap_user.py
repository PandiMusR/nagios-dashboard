#!/usr/bin/env python3
import sys
from ldap3 import Server, Connection, ALL

if len(sys.argv) != 3:
    print('Usage: python3 add_ldap_user.py <username> <password>')
    sys.exit(1)

username = sys.argv[1]
password = sys.argv[2]

server = Server('172.18.0.4', get_info=ALL)
conn = Connection(server, 'cn=admin,dc=bnet,dc=id', 'admin', auto_bind=True)

conn.add('ou=users,dc=bnet,dc=id', 'organizationalUnit')
conn.add('ou=groups,dc=bnet,dc=id', 'organizationalUnit')

group_dn = 'cn=nagiosadmins,ou=groups,dc=bnet,dc=id'
user_dn = f'uid={username},ou=users,dc=bnet,dc=id'

conn.add(group_dn, ['groupOfNames'], {
    'cn': 'nagiosadmins',
    'member': user_dn
})

uid_num = str(hash(username) % 10000 + 1000)
conn.add(user_dn, ['inetOrgPerson', 'posixAccount'], {
    'cn': username,
    'sn': 'User',
    'uid': username,
    'userPassword': password,
    'uidNumber': uid_num,
    'gidNumber': uid_num,
    'homeDirectory': f'/home/{username}'
})

conn.modify(group_dn, {'member': [('MODIFY_ADD', [user_dn])]})
print(f'User {username} created in nagiosadmins group')
conn.unbind()
