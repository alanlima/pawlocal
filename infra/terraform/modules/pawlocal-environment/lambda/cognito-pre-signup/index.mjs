export const handler = async (event) => {
  if (event.triggerSource === "PreSignUp_SignUp") {
    event.response.autoConfirmUser = true;
  }

  return event;
};
