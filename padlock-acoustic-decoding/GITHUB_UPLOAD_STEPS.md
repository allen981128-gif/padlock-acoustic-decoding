# GitHub upload steps

The remote repository already exists as:

`https://github.com/allen981128-gif/padlock-acoustic-decoding`

## Recommended: command line

1. Extract the prepared repository ZIP.
2. Open PowerShell in the extracted `padlock-acoustic-decoding` folder.
3. Run:

```powershell
git init
git add .
git commit -m "Dissertation submission snapshot"
git branch -M main
git remote add origin https://github.com/allen981128-gif/padlock-acoustic-decoding.git
git push -u origin main
```

GitHub may open a browser window for authentication.

## After the first push

Create a release/tag named `dissertation-v1.0`, then record the resulting commit SHA in the dissertation Appendix F.

Keep the repository private until public release has been reviewed with the supervisor.
