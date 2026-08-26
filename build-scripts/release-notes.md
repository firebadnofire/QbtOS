Every artifact includes a detached armored GPG signature with the same
filename plus `.asc`. Download both files, recover the signing key
using any one of these methods, and verify the artifact:

```sh
gpg --keyserver hkps://keys.openpgp.org --recv-keys 7D6EF134D851C8DA0862D97494F31AF374E2EE3C
# Or:
gpg --keyserver hkps://keyserver.ubuntu.com --recv-keys 7D6EF134D851C8DA0862D97494F31AF374E2EE3C
# Or:
curl --proto '=https' --tlsv1.2 -fsSLo william.asc https://archuser.org/gpg/william.asc
gpg --import william.asc

gpg --fingerprint 7D6EF134D851C8DA0862D97494F31AF374E2EE3C
gpg --verify <artifact>.asc <artifact>
```

Confirm the recovered key fingerprint is exactly
`7D6E F134 D851 C8DA 0862 D974 94F3 1AF3 74E2 EE3C` before trusting a
successful signature verification.
