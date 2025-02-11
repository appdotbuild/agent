# Feature Flags usage
# 1. import the feature flag
# 2. check the feature flag
# 3. if flag not set, continue app execution with no error
# 4. if flag is set and feature deployed, remove the flag check and remove the flag from the code

gherkin: bool = False 